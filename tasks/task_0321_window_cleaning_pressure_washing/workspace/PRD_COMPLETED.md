# Window Cleaning & Pressure Washing API — Product Requirements Document

## 1. Introduction

Residential and commercial exterior-cleaning operators juggle a deceptively complex book of work: every property is priced differently depending on whether the crew counts window panes or measures glass area, jobs recur on standing schedules or run once, field crews must be routed and dispatched within daily capacity, and the weather can void an entire day's plan at a moment's notice. This API is the system of record for a window-cleaning and pressure-washing business, governing the full arc from a first price quote through recurring service delivery, per-visit billing, deposit handling, and goodwill re-cleans when a customer is dissatisfied.

The platform serves four operational constituencies whose responsibilities rarely overlap. Customers obtain quotes, accept them, and convert them into standing service agreements; dispatchers build crews, plan routes, and commit visits onto those routes while respecting capacity and skill constraints; field crews execute the work on site, documenting it with before-and-after photography; and the billing office reconciles deposits, raises invoices against completed work, and adjudicates re-clean requests. Because money, scheduling, and weather all interact — a deposit gates activation, a capacity ceiling gates routing, a weather suspension forces a reschedule that in turn earns a goodwill discount — the system must reconcile derived balances and booked-time totals immediately and consistently after every mutation.

This document specifies the contract for that system: the resource model, the parallel and cyclic state machines that govern each entity, the dual-variant pricing and charging calculations, the priority-ordered validation rules, and the role-based access boundaries that keep each constituency inside its lane.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint. The business workflows that consume these principles are detailed in Section 3.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers. The `X-User-ID` header identifies the acting user, and the `X-User-Role` header declares the operational capacity under which the request is made. If either header is missing or blank, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles, spelled precisely as follows: `Customer`, `Dispatcher`, `FieldCrew`, and `Billing`. A `Customer` is an account holder who manages their own properties, quotes, service agreements, deposits, and re-clean requests. A `Dispatcher` owns the operational fleet — crews, routes, weather advisories, and the scheduling and field-status flow of visits. A `FieldCrew` executes the work on a route: uploading photos, starting and completing visits, and attaching on-site add-ons. The `Billing` role owns deposits, invoices, the account ledger, agreement activation and completion, re-clean adjudication, and the test-only clock.

Identity binds to ownership differently per role. When `X-User-Role` is `Customer`, the `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's account foreign key to `X-User-ID`. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same holds for `FieldCrew`: its `X-User-ID` is an opaque operator identifier that is not matched against any stored entity. Likewise, when `X-User-Role` is `Billing`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity and is never compared to an entity's `id`.

Some operations are exclusive to one role while others are shared. Account, property, quote, and quote-send creation, service-agreement conversion, and deposit posting are shared between `Customer` and `Billing`. Accepting, declining, pausing, resuming, and cancelling are reserved to the `Customer`, and only a `Customer` may open a re-clean request. Crew, route, weather-advisory, scheduling, weather-reschedule, and visit-cancel operations are exclusive to the `Dispatcher`. Photo upload and the visit start/complete pair are exclusive to the `FieldCrew`, while attaching an add-on to a visit is shared between `Dispatcher` and `FieldCrew`. Agreement activation and completion, invoicing and payment, re-clean approval and denial, and advancing the test clock are reserved to `Billing`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter sets how many items to skip from the front of the result and defaults to 0.

Unless an endpoint states otherwise, list results are sorted by their creation timestamp, `created_at`, in ascending order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Resource Identity

Most resources in the system share a standard set of system-managed fields. Each carries an `id` — a server-minted UUID with no type prefix — along with a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Both timestamps are ISO 8601 UTC values with three fractional digits. The `created_at` field is fixed at creation; `updated_at` is refreshed on every mutation; and `version` begins at `1` at creation and increments by one with each mutation, serving as the basis for optimistic concurrency control where applicable.

Two entities are deliberately leaner. A `VisitPhoto` and a `LedgerEntry` are append-only records: each carries only an `id` and a `created_at` and is never mutated in place. For these two entity types there is no `updated_at` field and no `version` field at all — they are written once and thereafter only read.

Whenever a derived field is recomputed — an account's balance, a route's booked minutes, a visit's stamped charge — and the recomputed value actually differs from the stored one, the change is treated as a mutation of the owning resource: its `updated_at` is refreshed and its `version` increments. This holds even when the recomputation is triggered indirectly by an action on a different entity; when a recomputation lands on the same value already stored, neither `updated_at` nor `version` changes.

### 2.5. Nested Resource Retrieval and Referential Integrity

Several read endpoints address a resource through a parent path segment — for example, the photos or add-ons belonging to a particular visit, or the properties, quotes, deposits, invoices, ledger entries, or service agreements belonging to a particular account. For any such path, identifiers are validated left to right: the system confirms the parent exists before it looks for the child, and the first identifier in the path that does not resolve produces `ERR_NOT_FOUND`. Any referenced resource — whether named in the path or supplied in the body — that does not exist yields `ERR_NOT_FOUND` as well.

Existence is not sufficient on its own. On creation and commit operations, foreign keys must not only resolve but also belong together. A quote's property must itself belong to the quote's account; a visit's agreement must resolve; a route's crew must resolve. When referenced resources exist individually but are not consistent with one another — for instance, a quote whose `property_id` points at a property owned by a different account than the quote's `account_id` — the request is rejected with `ERR_REFERENTIAL_MISMATCH`. This referential consistency check applies to quote creation, service-agreement conversion, committing a visit onto a route, and invoice creation.

### 2.6. Monetary Precision and Rounding

All monetary amounts in this system are represented and stored as whole integer cents; there are no fractional-cent values anywhere in the model. Wherever a calculation introduces a fractional result — a percentage surcharge, a percentage discount, a per-square-foot rate applied to a non-integer area — the result is rounded to the nearest whole cent using the round-half-up convention, meaning a value exactly halfway between two cents rounds upward.

A pinning rule governs how multi-component totals are assembled: each component is rounded to whole cents independently, and only then are the rounded components summed. The system never sums raw fractional components and rounds once at the end. This "round each line, then add" discipline applies to quote totals, add-on totals, and every other place where a total is built from separately-rounded parts.

### 2.7. Derived Balances and the Account Ledger

Each `Account` exposes two computed money fields and never lets a client write them directly. The `balance_cents` field is the running sum of the `signed_amount_cents` of every `LedgerEntry` posted against the account; a positive balance is money owed by the customer and a negative balance is customer credit, and it starts at zero. The `deposit_held_cents` field is the sum of `amount_cents` across all of the account's deposits that remain in `HELD` status, and it likewise starts at zero. Both are recomputed immediately whenever any contributing ledger entry or deposit changes.

The ledger is append-only and polymorphic. Every `LedgerEntry` records the `account_id` it posts against, a `source_type` drawn from `INVOICE`, `PAYMENT`, `DEPOSIT`, or `RECLEAN_CREDIT`, a `source_id` pointing at the originating row (an `Invoice`, a payment, a `Deposit`, or a `ReCleanRequest`, resolved according to `source_type`), and a `signed_amount_cents` whose sign carries its meaning: a positive value is a debit that raises the balance owed, and a negative value is a credit that lowers it. The sign convention is the single mechanism by which invoices, payments, deposit movements, and goodwill credits all flow into one balance.

### 2.8. Route Capacity and Crew Exclusivity

A route's booked time, `booked_minutes`, is a derived field: it is the sum of the `duration_minutes` of every visit committed to that route whose schedule status is `SCHEDULED`, `DISPATCHED`, `IN_PROGRESS`, or `COMPLETED`, and it starts at zero. Whenever a visit is committed, pulled off, or cancelled, the affected route's `booked_minutes` is recomputed accordingly. Each crew advertises a `daily_capacity_minutes` ceiling, and a route may never be loaded past that crew's ceiling.

Crews are also bound by whole-day exclusivity. A single crew may hold at most one route per calendar `service_date` that is not yet `CLOSED`. Two routes for the same crew on the same calendar date collide regardless of any minute-level window, and the second attempt is rejected with `ERR_CREW_DOUBLE_BOOKED`.

### 2.9. Optimistic Concurrency on Route Commitment

Committing a visit onto a route is the one operation guarded by optimistic concurrency control, because each successful commit consumes route capacity and advances `version` on the route. The commit request must carry an `expected_route_version` field whose value is the client's last observed `version` of the target route. If that value does not equal the route's current `version` — that is, if another writer has committed a visit and advanced the route's version since the client last read it — the commit is rejected with `ERR_STALE_ROUTE_VERSION` and HTTP status 412. This prevents a writer from reasoning about capacity and window overlap against an outdated `booked_minutes` snapshot and overwriting a commit it never observed. The `expected_route_version` field is mandatory on this operation; no other endpoint in the system takes a version field, and none performs an OCC check.

### 2.10. Quote Expiry by the Logical Clock

The system maintains a logical "current" UTC instant that drives quote expiry. Every quote carries a `valid_until` instant. A quote that is still in `DRAFT` or `SENT` automatically transitions to `EXPIRED` the moment the current clock reaches or passes `valid_until`; this is evaluated lazily, on any read or transition that touches the quote. The clock is advanced for testing through an administrative capability that sets the server's current UTC instant from a supplied value; subsequent lazy-expiry checks use that instant.

## 3. Business Logic & Workflows

### 3.1. Accounts, Properties, and the Quoting Engine

The customer relationship begins with an `Account`, created with a `company_name`, a `contact_email`, and a `region_code`. The contact email must be unique across all accounts — a creation whose `contact_email` collides with an existing account is rejected with `ERR_INVALID_REQUEST` — and the region must be one of `NORTH`, `SOUTH`, `EAST`, or `WEST` — the same four regions used throughout the system to match crews, routes, and weather advisories. Every account is born in `status` `ACTIVE` and stays there; there is no suspension lifecycle in this domain. Its `balance_cents` and `deposit_held_cents` both begin at zero and are derived thereafter as described in the ledger principles.

Under an account, a `Customer` registers one or more properties. A `Property` records its owning `account_id`, an `address_line`, a `pane_count` (the number of window panes, which must be zero or greater), a `glass_sqft` (the total glass area in square feet, also zero or greater), a `stories` count (the number of building stories, at least one), and a `soft_wash_sqft` (the exterior surface area eligible for soft-wash pressure washing, which defaults to 0 when omitted and must be zero or greater). The pane count and glass area are the two competing bases for pricing; the story count drives a high-rise surcharge; and the soft-wash area feeds the soft-wash add-on.

A `Quote` is priced against one property. It records the `account_id` and `property_id` it is for, a `pricing_basis` that selects the quoting variant (`PANE_COUNT` or `SQ_FT`), an optional list of `addon_codes` (a subset of `GUTTER`, `SCREEN`, and `SOFT_WASH`, defaulting to an empty list), and a `valid_until` instant after which the quote may no longer be accepted. From these inputs the system computes four money fields — `base_price_cents`, `addon_total_cents`, `quoted_total_cents`, and `required_deposit_cents` — at creation time, and a quote opens in `status` `DRAFT`.

The **base window-cleaning price** depends entirely on the chosen basis, and the two variants never blend. Under the `PANE_COUNT` basis, the system ignores glass area and prices the pane count through marginal tiers: the first 20 panes are charged at 300 cents each; panes 21 through 50 (up to the next 30 panes) at 250 cents each; and every pane beyond 50 at 200 cents each. The three tier contributions are summed to form the raw base. Under the `SQ_FT` basis, the system ignores the pane count entirely, rounds the glass area up to the next whole square foot, and multiplies that whole number of square feet by 90 cents. A property with both fields populated will generally yield a different total under each basis, which is exactly why the basis is an explicit input. Under either basis, the raw base is then floored at a job minimum of 9,900 cents: if the computed base is below that minimum, the base becomes 9,900 cents.

A **high-rise surcharge** is applied combinatorially on top of the floored base. When the property's `stories` count is at least 3, a surcharge equal to 20 percent of the base — rounded to whole cents, half-up — is added to the base; below 3 stories no surcharge applies. The result of the floor-then-surcharge sequence is the quote's `base_price_cents`.

**Add-on charges** are computed independently and each rounded to whole cents before being summed into `addon_total_cents`. If `GUTTER` is requested, a flat 7,500 cents is added. If `SCREEN` is requested, 150 cents is added for each pane of the property (150 cents multiplied by the property's pane count). If `SOFT_WASH` is requested, the soft-wash line is the property's soft-wash square footage multiplied by 25 cents and rounded half-up to whole cents, and that rounded line is then raised to a floor of 12,000 cents — whichever of the rounded line and 12,000 cents is larger is what the soft-wash add-on contributes. The quote's `quoted_total_cents` is the sum of the already-whole-cent `base_price_cents` and `addon_total_cents`; following the pinning rule, each component is a whole-cent figure before they are added.

The **required deposit** is a threshold calculation over the quote's total. When `quoted_total_cents` is at least 30,000 cents, the `required_deposit_cents` is 25 percent of the quoted total, rounded half-up to whole cents. When the quoted total is below 30,000 cents, no deposit is required and `required_deposit_cents` is 0.

A quote in `DRAFT` is sent to the customer, transitioning it to `SENT`. Sending recomputes and then **freezes** all four priced fields — `base_price_cents`, `addon_total_cents`, `quoted_total_cents`, and `required_deposit_cents` — so that they become immutable from that point forward. From `SENT`, the customer may accept it, moving it to `ACCEPTED`, provided the current clock has not reached the quote's `valid_until`; an accept attempt past that instant is rejected as expired with `ERR_QUOTE_EXPIRED`, and the quote is treated as `EXPIRED`. Alternatively, the customer may decline a `SENT` quote, moving it to `DECLINED`. Any quote still in `DRAFT` or `SENT` lazily becomes `EXPIRED` once the clock reaches `valid_until`. Reading a quote whose clock has passed surfaces this `EXPIRED` transition. The states `DECLINED`, `EXPIRED`, and `CONVERTED` are terminal.

### 3.2. Converting a Quote into a Service Agreement

An `ACCEPTED` quote is the gateway to a standing relationship. Converting it creates a `ServiceAgreement` and simultaneously moves the quote from `ACCEPTED` to `CONVERTED`. The conversion request names the source quote and the `schedule_kind` — either `ONE_TIME` or `RECURRING` — and, for recurring work, a `recurrence_interval_days`. For a `RECURRING` agreement the interval is required and must be at least 7 days; for a `ONE_TIME` agreement the interval is ignored. A conversion attempted against a quote whose `valid_until` has passed is rejected as expired with `ERR_QUOTE_EXPIRED`.

The new agreement records the `account_id` and `property_id` copied from the quote and the originating `quote_id`. At conversion the agreement snapshots two money figures from the quote: its `per_visit_price_cents` is set to the quote's `quoted_total_cents`, and its `required_deposit_cents` is set to the quote's `required_deposit_cents`. These snapshots fix the standing estimate charged per completed visit and the deposit the agreement must secure. A `visits_generated_count` tracks how many visits the agreement has produced and starts at 0. A freshly converted agreement opens in `status` `PENDING_DEPOSIT`.

An agreement in `PENDING_DEPOSIT` is activated by the billing office once its deposit obligation is met — specifically, once the sum of the account's `HELD` deposits standing against this agreement reaches at least the agreement's `required_deposit_cents`. If that threshold is not met, activation is rejected with `ERR_DEPOSIT_NOT_MET`. Activation carries inputs that seed the first visit: a `first_visit_planned_date`, a `first_visit_window_start_min`, and a `first_visit_window_end_min`. On a successful activation the agreement moves to `ACTIVE`, the system generates the first `Visit` in `UNSCHEDULED` status for the agreement's property using those window inputs, and the `visits_generated_count` becomes 1.

While `ACTIVE`, an agreement is the basis for visit generation and routing. The customer may pause an `ACTIVE` agreement, moving it to `PAUSED`; pausing cancels every one of this agreement's visits that is currently in schedule status `SCHEDULED`, transitioning each to `CANCELLED` and decrementing the `booked_minutes` of whatever route each was committed to. A `PAUSED` agreement may be resumed back to `ACTIVE`, completing the cyclic `ACTIVE` ↔ `PAUSED` relationship. The billing office may complete an `ACTIVE` agreement, moving it to `COMPLETED`, but only when no open work remains: for a `ONE_TIME` agreement its single visit must be in schedule status `COMPLETED`, and for a `RECURRING` agreement no visit may remain in `SCHEDULED`, `DISPATCHED`, or `IN_PROGRESS`. A completion attempted with open visits is rejected with `ERR_OPEN_VISITS_EXIST`. On completion, each `HELD` deposit for the agreement transitions to `REFUNDED`, and for each refunded deposit a `LedgerEntry` with `source_type` `DEPOSIT`, `source_id` set to that deposit, and a `signed_amount_cents` equal to the negative of the deposit's amount is posted, after which the account's `balance_cents` and `deposit_held_cents` are recomputed.

An agreement may be cancelled by the customer from `PENDING_DEPOSIT`, `ACTIVE`, or `PAUSED`, moving it to `CANCELLED`. Cancellation cancels every one of this agreement's visits still in schedule status `SCHEDULED` or `UNSCHEDULED` (each moves to `CANCELLED`, and for any that sat on a route the route's `booked_minutes` is decremented), and it refunds every `HELD` deposit for the agreement exactly as completion does — each deposit moves to `REFUNDED`, a `DEPOSIT` `LedgerEntry` carrying the negative of the deposit amount is posted, and the account's `balance_cents` and `deposit_held_cents` are recomputed. Both `COMPLETED` and `CANCELLED` are terminal.

### 3.3. Deposits and Crews

A `Deposit` is posted against an account and an agreement, carrying an `account_id`, an `agreement_id`, and an `amount_cents` that must be greater than zero. A newly posted deposit opens in `HELD` status. Posting a deposit immediately writes a `DEPOSIT` `LedgerEntry` debit equal to the positive deposit amount and recomputes the account's `deposit_held_cents` and `balance_cents`. A deposit's lifecycle is driven entirely by other entities: it moves to `APPLIED` only when an invoice's settlement fully consumes it, and to `REFUNDED` when its owning agreement is completed or cancelled. Both `APPLIED` and `REFUNDED` are terminal.

The fleet is built from crews. A `Crew` carries a `crew_name`, a `region_code` it serves (one of the four regions), a list of `skill_codes` (a subset of `SOFT_WASH` and `HIGH_RISE`, defaulting to empty), and a `daily_capacity_minutes` that must be greater than zero. A crew opens `AVAILABLE`. The dispatcher may toggle a crew's availability by setting its status: an `AVAILABLE` crew can be set `OFFLINE`, and an `OFFLINE` crew can be set back to `AVAILABLE`, with the desired `status` supplied on the request. An `OFFLINE` crew cannot have its routes dispatched. A crew's skill set matters at commit time: any visit that requires a skill the crew lacks cannot be committed to that crew's route.

### 3.4. Building Routes and Committing Visits

A `Route` represents one crew's run on one calendar day. The dispatcher creates a route by naming the `crew_id`, the `region_code`, and the `service_date` (a `YYYY-MM-DD` calendar date). The route's region must equal the crew's region. A route opens in `PLANNING` status with `booked_minutes` at zero. Route creation honors the whole-day crew-exclusivity rule: if the crew already holds a non-`CLOSED` route on the same `service_date`, the new route is rejected with `ERR_CREW_DOUBLE_BOOKED`.

A `Visit` is the unit of fieldwork. It records the `agreement_id` that generated it, the `property_id` copied from that agreement at generation, and — once committed — the `route_id` of the route it is committed to (null until committed). It carries a `planned_date`, a `window_start_min` and a `window_end_min` expressed as minutes from midnight, and a computed `duration_minutes` equal to the window end minus the window start. The window is half-open: `window_start_min` must be at least 0 and strictly less than `window_end_min`, and `window_end_min` must be at most 1440. Each visit also exposes a computed `requires_soft_wash` flag (true when the source quote's add-on codes include `SOFT_WASH`), a computed `requires_high_rise` flag (true when the property's `stories` count is at least 3), a `reschedule_count` that starts at 0, and a `charge_amount_cents` that is stamped only at completion. A visit carries two independent status dimensions: a `schedule_status` that begins `UNSCHEDULED` and a `billing_status` that begins `UNBILLED`; the two evolve independently of one another.

Committing an `UNSCHEDULED` visit onto a `PLANNING` route is the heart of dispatch, and it is heavily guarded. The commit request supplies the `visit_id` being committed and the `expected_route_version` for the optimistic-concurrency check. The visit's schedule status must be `UNSCHEDULED`. The route must be in `PLANNING`, or the commit is rejected with `ERR_ROUTE_NOT_PLANNING`. The visit's agreement must be `ACTIVE`, or the commit is rejected with `ERR_AGREEMENT_NOT_ACTIVE`. The visit's region — its account's `region_code` — must equal the route's `region_code`, or the commit is rejected with `ERR_REGION_MISMATCH`. If the visit requires soft-wash work, the crew's `skill_codes` must include `SOFT_WASH`; if the visit requires high-rise work, the crew's `skill_codes` must include `HIGH_RISE`; a missing skill in either case is rejected with `ERR_CREW_SKILL_MISSING`. The visit's `planned_date` must equal the route's `service_date`, or the commit is rejected with `ERR_DATE_MISMATCH`. Adding the visit's duration to the route's current `booked_minutes` must not exceed the crew's `daily_capacity_minutes`, or the commit is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`. The visit's service window must not overlap any visit already on the route whose schedule status is `SCHEDULED`, `DISPATCHED`, or `IN_PROGRESS`; because windows are half-open intervals, two windows that merely touch at an endpoint do not overlap, but any true overlap is rejected with `ERR_VISIT_WINDOW_OVERLAP`. Finally, the `expected_route_version` must match the route's current `version`, or the commit is rejected with `ERR_STALE_ROUTE_VERSION`.

When every check passes, the visit's schedule status advances from `UNSCHEDULED` to `SCHEDULED`, the visit's `route_id` is set to the route, the route's `booked_minutes` is recomputed to include the visit's duration, and the route's `version` increments by one. The route-version increment is precisely what makes a subsequently-arriving stale commit fail the optimistic-concurrency check.

A dispatcher dispatches a `PLANNING` route, moving it to `DISPATCHED`, provided its crew is `AVAILABLE` (otherwise `ERR_CREW_OFFLINE`) and at least one visit is committed to it (otherwise `ERR_EMPTY_ROUTE`). Dispatching cascades to every committed visit: each visit in schedule status `SCHEDULED` advances to `DISPATCHED`. A `DISPATCHED` route is closed, moving to `CLOSED`, only when no committed visit remains in `DISPATCHED` or `IN_PROGRESS` — every committed visit must be `COMPLETED` or `CANCELLED` — otherwise the close is rejected with `ERR_OPEN_VISITS_EXIST`. `CLOSED` is terminal for a route.

### 3.5. Executing a Visit: Photos, Add-Ons, Start, and Completion

Field execution revolves around photographic documentation. A `VisitPhoto` records the `visit_id` it documents, a `phase` of either `BEFORE` or `AFTER`, and an opaque `image_uri`. Photos are append-only and may be uploaded freely as the crew works.

On-site, a field crew or dispatcher may attach add-ons to a visit. A `VisitAddOn` records the `visit_id` it is attached to and an `addon_code` of `GUTTER`, `SCREEN`, or `SOFT_WASH`, and the system computes its `charge_cents` at attach time over the visit's property, mirroring the quote's add-on rules: a `GUTTER` add-on is a flat 7,500 cents; a `SCREEN` add-on is 150 cents multiplied by the property's pane count; and a `SOFT_WASH` add-on is the property's soft-wash square footage multiplied by 25 cents and rounded half-up to whole cents, then raised to a floor of 12,000 cents (the larger of that rounded line and 12,000 cents). Add-ons attached or detached after a visit is generated are what let the eventual charge diverge from the standing estimate.

A `DISPATCHED` visit is started by the field crew, advancing its schedule status to `IN_PROGRESS`, but only when exactly one `BEFORE`-phase photo exists for the visit; starting without that before photo is rejected with `ERR_BEFORE_PHOTO_REQUIRED`. An `IN_PROGRESS` visit is completed by the field crew, advancing its schedule status to `COMPLETED`, but only when at least one `AFTER`-phase photo exists; completing without an after photo is rejected with `ERR_AFTER_PHOTO_REQUIRED`.

Completion is where the **actual per-visit charge** is stamped, and it may diverge from the agreement's standing estimate. The charge starts from the agreement's `per_visit_price_cents` as its base. To that base is added the sum of the `charge_cents` of every `VisitAddOn` currently attached to the visit, producing a gross figure. If the visit's `reschedule_count` is at least 2, a goodwill discount of 10 percent of the gross — rounded half-up to whole cents — is subtracted from the gross; with fewer than two reschedules no discount applies. The visit's `charge_amount_cents` is the resulting figure, floored at 0 so it never goes negative. Before completion, the estimate for a generated visit simply equals the agreement's `per_visit_price_cents`; the add-on deltas and reschedule discount are reflected only in the actual charge stamped at completion, so the same visit can complete at a different cents value than its estimate.

Completion also drives recurrence. When a `RECURRING` agreement's visit completes, the system generates the next `Visit` in `UNSCHEDULED` status, dated at the just-completed visit's `planned_date` plus the agreement's `recurrence_interval_days`, and increments the agreement's `visits_generated_count`. If the completing visit happens to be a re-clean remedy visit, completing it also resolves its originating re-clean request, as described below.

### 3.6. Weather Reschedules and Visit Cancellation

Weather is the recurring disruptor of field schedules. A `WeatherAdvisory` is registered by the dispatcher for a `region_code`, an `advisory_date` (the `YYYY-MM-DD` calendar date it covers), and a `severity` of either `ADVISORY` (purely informational) or `SUSPEND` (which gates weather-reschedule eligibility). Only a `SUSPEND`-severity advisory enables a reschedule.

A weather reschedule pulls a `SCHEDULED` visit off its route and re-targets it to a new date. It is permitted only when the visit is in schedule status `SCHEDULED` and a `SUSPEND`-severity advisory whose `region_code` matches the route's region covers the visit's `planned_date`; absent such a hold, the reschedule is rejected with `ERR_NO_WEATHER_HOLD`. The request supplies a `new_planned_date`. On reschedule, the old route's `booked_minutes` is recomputed downward by the visit's duration, the visit's `route_id` is cleared to null, its schedule status returns to `UNSCHEDULED`, its `planned_date` is set to the supplied `new_planned_date`, and its `reschedule_count` increments by one. The visit can then be committed onto a future-date route whose `service_date` matches the new planned date, re-entering `SCHEDULED`. Reschedules accumulate on `reschedule_count`, which is exactly the counter that triggers the goodwill discount at completion once it reaches two.

Separately, a dispatcher may cancel a visit while it is in schedule status `UNSCHEDULED` or `SCHEDULED`, moving it to `CANCELLED`. If the visit was committed to a route, that route's `booked_minutes` is recomputed downward by the visit's duration and the visit's `route_id` is cleared. `CANCELLED` is terminal on the schedule dimension.

### 3.7. Per-Visit Billing, Invoices, and Payment

The billing dimension of a visit evolves independently of its scheduling. Once a visit's schedule status is `COMPLETED`, the billing office may invoice it, moving the visit's `billing_status` from `UNBILLED` to `INVOICED`; invoicing a visit that is not yet `COMPLETED` is rejected with `ERR_VISIT_NOT_COMPLETED`. There is at most one invoice per visit: an invoice request naming a `visit_id` that already has an invoice is rejected with `ERR_DUPLICATE_INVOICE`.

An `Invoice` records the `account_id` (copied from the visit's agreement), the `visit_id` being billed, an `amount_cents` snapshotted from the visit's `charge_amount_cents` at invoice creation, a `deposit_applied_cents`, and a `net_due_cents`. It opens in `ISSUED` status. The deposit is applied through a **waterfall**: the system walks the agreement's `HELD` deposits oldest first (ordered by their `created_at` ascending) and consumes them against the invoice amount, taking from each deposit the smaller of that deposit's remaining amount and the still-unpaid remainder of the invoice, accumulating the consumed total, and stopping once the invoice is fully covered. A deposit that is consumed in full transitions to `APPLIED`; a deposit only partially consumed remains `HELD`. The total consumed becomes `deposit_applied_cents`, and the `net_due_cents` is the invoice amount minus the applied deposit, which by construction is never negative. Settling the invoice posts an `INVOICE` debit `LedgerEntry` for the net due and, when a deposit was applied, a `DEPOSIT` credit `LedgerEntry`, after which the account's `balance_cents` is recomputed.

An `INVOICED` invoice is paid by the billing office, moving the invoice to `PAID` and the visit's `billing_status` to `PAID`. Payment posts a `PAYMENT` credit `LedgerEntry` for the net due amount and recomputes the account's `balance_cents`. The `VOID` invoice status exists for re-clean reversals, described next. A visit's billing may also be `WAIVED` outright — this happens when an `UNBILLED` visit is the subject of an approved re-clean, in which case no invoice is ever raised for it.

### 3.8. Satisfaction Re-Cleans

When a customer is dissatisfied with a `COMPLETED` visit, they open a `ReCleanRequest` naming the `visit_id` and a free-text `reason`. The request opens in `REQUESTED` status and carries two fields that stay empty until adjudication: a `remedy_visit_id` (the no-charge remedy visit synthesized on approval) and a `credit_cents` (the goodwill credit posted on approval), both null or zero until then.

The billing office adjudicates each request. Approval is permitted only from `REQUESTED` and only when the target visit's schedule status is `COMPLETED`, otherwise `ERR_VISIT_NOT_COMPLETED`. The **goodwill credit** is keyed on how well the original work was documented. The system counts the `AFTER`-phase photos on file for the target visit; since a completed visit always has at least one after photo, the count is at least one. When two or more after photos are on file, the work is considered well-documented and earns only a partial credit of 50 percent of the visit's `charge_amount_cents`, rounded half-up to whole cents. When exactly one after photo is on file, the work is considered thinly documented and earns a full credit equal to the visit's entire `charge_amount_cents`.

On approval the request moves to `APPROVED` and three effects fire together. First, the computed `credit_cents` is stamped and a `RECLEAN_CREDIT` `LedgerEntry` carrying the negative of that credit is posted, after which the account's `balance_cents` is recomputed. Second, the billing of the unsatisfactory visit is unwound: if the target visit's billing status is still `UNBILLED`, it becomes `WAIVED` and no invoice will ever be raised; if it was already `INVOICED`, the matching invoice is set to `VOID` and its `INVOICE` debit is reversed. Third, the system synthesizes a no-charge remedy `Visit` in `UNSCHEDULED` schedule status on the same agreement, with its charge waived, and sets the request's `remedy_visit_id` to the new visit. Alternatively, the billing office may deny a `REQUESTED` request, moving it to `DENIED` with no further effect. Once the synthesized remedy visit itself reaches schedule status `COMPLETED`, the originating request advances from `APPROVED` to `RESOLVED`. Both `DENIED` and `RESOLVED` are terminal.

### 3.9. Validation Ordering and the Logical Clock

Across every endpoint, validations are applied in a fixed priority order so that the same scenario always surfaces the same error. Authentication comes first: a request missing either auth header fails with `ERR_UNAUTHENTICATED` before anything else. Authorization is next: a role not permitted for the operation fails with `ERR_UNAUTHORIZED`. Then existence is checked, with every referenced resource validated left to right and a miss yielding `ERR_NOT_FOUND`. Referential consistency follows, rejecting mismatched foreign keys with `ERR_REFERENTIAL_MISMATCH`. Only then are state-and-business rules evaluated.

Within the state-and-business tier the ordering continues to matter. The generic "transition not defined from the current state" guard yields `ERR_INVALID_STATE` and is evaluated before the more specific business-state checks it might otherwise mask. Quote-expiry (`ERR_QUOTE_EXPIRED`) precedes agreement-active (`ERR_AGREEMENT_NOT_ACTIVE`), which precedes route-planning (`ERR_ROUTE_NOT_PLANNING`), which precedes the visit-completed guard (`ERR_VISIT_NOT_COMPLETED`), which precedes the crew-availability guard (`ERR_CREW_OFFLINE`). After those state guards come the business-safety checks — crew skill coverage (`ERR_CREW_SKILL_MISSING`) and the photo requirements (`ERR_BEFORE_PHOTO_REQUIRED` for start, `ERR_AFTER_PHOTO_REQUIRED` for complete) — then the business-constraint and temporal checks: region match (`ERR_REGION_MISMATCH`), date match (`ERR_DATE_MISMATCH`), window overlap (`ERR_VISIT_WINDOW_OVERLAP`), and the weather-hold requirement (`ERR_NO_WEATHER_HOLD`). The fiscal checks — route capacity (`ERR_ROUTE_CAPACITY_EXCEEDED`) and deposit-met (`ERR_DEPOSIT_NOT_MET`) — come next, followed by the duplicate-invoice guard (`ERR_DUPLICATE_INVOICE`), the optimistic-concurrency stale-route check (`ERR_STALE_ROUTE_VERSION`), the open-visits guard for closing routes and completing agreements (`ERR_OPEN_VISITS_EXIST`), the empty-route guard for dispatch (`ERR_EMPTY_ROUTE`), and the crew double-booking guard for route creation (`ERR_CREW_DOUBLE_BOOKED`). Underpinning all of these, every create and transition request must carry well-formed, well-typed body fields with in-range enums — and a `RECURRING` agreement conversion must include a `recurrence_interval_days` of at least 7 — or the request is rejected with `ERR_INVALID_REQUEST`.

To support deterministic testing of quote expiry, an administrative capability advances the server's logical clock to a supplied `to_iso8601` instant. Subsequent lazy-expiry evaluations compare each quote's `valid_until` against that instant.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — an account, a property, a quote, a service agreement, a deposit, a crew, a route, a weather advisory, a committed visit, a visit add-on, a visit photo, an invoice, or a re-clean request — return a `201 Created` status code. Operations that modify an existing resource, including every state transition and the administrative clock advance, return a `200 OK` status code. The request and response payloads for each endpoint are not enumerated here; they are reconstructed from the business narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Create a customer account | Customer, Billing |
| GET | `/accounts/{id}` | Read an account | Customer, Billing, Dispatcher |
| GET | `/accounts/{id}/ledger-entries` | List an account's ledger entries | Billing, Customer |
| GET | `/accounts/{id}/properties` | List an account's properties | Customer, Billing, Dispatcher |
| GET | `/accounts/{id}/deposits` | List an account's deposits | Billing, Customer |
| GET | `/accounts/{id}/invoices` | List an account's invoices | Billing, Customer |
| GET | `/accounts/{id}/service-agreements` | List an account's agreements | Customer, Billing |
| GET | `/accounts/{id}/quotes` | List an account's quotes | Customer, Billing |
| POST | `/properties` | Register a property under an account | Customer, Billing |
| GET | `/properties/{id}` | Read a property | Customer, Billing, Dispatcher |
| POST | `/quotes` | Create a DRAFT quote | Customer, Billing |
| GET | `/quotes` | List quotes, filterable by property or account | Customer, Billing |
| GET | `/quotes/{id}` | Read a quote (lazily expires) | Customer, Billing |
| POST | `/quotes/{id}/send` | Send a quote, freezing priced fields | Customer, Billing |
| POST | `/quotes/{id}/accept` | Accept a sent quote | Customer |
| POST | `/quotes/{id}/decline` | Decline a sent quote | Customer |
| POST | `/service-agreements` | Convert an accepted quote into an agreement | Customer, Billing |
| GET | `/service-agreements` | List agreements, filterable by property or quote | Customer, Billing, Dispatcher |
| GET | `/service-agreements/{id}` | Read an agreement | Customer, Billing, Dispatcher |
| GET | `/service-agreements/{id}/visits` | List an agreement's visits | Customer, Billing, Dispatcher |
| GET | `/service-agreements/{id}/deposits` | List an agreement's deposits | Billing, Customer |
| POST | `/service-agreements/{id}/activate` | Activate an agreement and generate the first visit | Billing |
| POST | `/service-agreements/{id}/pause` | Pause an active agreement | Customer |
| POST | `/service-agreements/{id}/resume` | Resume a paused agreement | Customer |
| POST | `/service-agreements/{id}/complete` | Complete an agreement, refunding deposits | Billing |
| POST | `/service-agreements/{id}/cancel` | Cancel an agreement, cancelling visits and refunding deposits | Customer |
| POST | `/deposits` | Post a deposit on an account/agreement | Billing, Customer |
| GET | `/deposits/{id}` | Read a deposit | Billing, Customer |
| POST | `/crews` | Create a crew | Dispatcher |
| GET | `/crews/{id}` | Read a crew | Dispatcher, Billing |
| POST | `/crews/{id}/set-status` | Set a crew available or offline | Dispatcher |
| POST | `/routes` | Create a planning route for a crew on a date | Dispatcher |
| GET | `/routes` | List routes, filterable by crew or service date | Dispatcher, Billing |
| GET | `/routes/{id}` | Read a route | Dispatcher, Billing |
| GET | `/routes/{id}/visits` | List visits committed to a route | Dispatcher, Billing, FieldCrew |
| POST | `/routes/{id}/visits` | Commit an unscheduled visit onto a route | Dispatcher |
| POST | `/routes/{id}/dispatch` | Dispatch a route, cascading its visits | Dispatcher |
| POST | `/routes/{id}/close` | Close a dispatched route | Dispatcher |
| GET | `/visits` | List visits, filterable by property, agreement, or route | Customer, Billing, Dispatcher, FieldCrew |
| GET | `/visits/{id}` | Read a visit | Customer, Billing, Dispatcher, FieldCrew |
| GET | `/visits/{id}/add-ons` | List a visit's add-ons | Customer, Billing, Dispatcher, FieldCrew |
| GET | `/visits/{id}/photos` | List a visit's before/after photos | Customer, Billing, Dispatcher, FieldCrew |
| POST | `/visits/{id}/add-ons` | Attach an add-on to a visit | Dispatcher, FieldCrew |
| POST | `/visits/{id}/photos` | Upload a before/after photo for a visit | FieldCrew |
| POST | `/visits/{id}/start` | Start a dispatched visit | FieldCrew |
| POST | `/visits/{id}/complete` | Complete a visit, stamping its charge | FieldCrew |
| POST | `/visits/{id}/weather-reschedule` | Pull a visit off its route under a weather hold | Dispatcher |
| POST | `/visits/{id}/cancel` | Cancel an unscheduled or scheduled visit | Dispatcher |
| GET | `/visits/{id}/reclean-requests` | List a visit's re-clean requests | Customer, Billing |
| POST | `/weather-advisories` | Register a weather advisory for a region/date | Dispatcher |
| GET | `/weather-advisories/{id}` | Read a weather advisory | Dispatcher |
| POST | `/invoices` | Invoice a completed visit | Billing |
| GET | `/invoices` | List invoices, filterable by visit or account | Billing, Customer |
| GET | `/invoices/{id}` | Read an invoice | Billing, Customer |
| POST | `/invoices/{id}/pay` | Pay an issued invoice | Billing |
| POST | `/reclean-requests` | Open a re-clean request for a completed visit | Customer |
| GET | `/reclean-requests/{id}` | Read a re-clean request | Customer, Billing |
| POST | `/reclean-requests/{id}/approve` | Approve a re-clean, posting credit and synthesizing a remedy | Billing |
| POST | `/reclean-requests/{id}/deny` | Deny a re-clean request | Billing |
| POST | `/_clock/set_current_utc` | Test-only: set the server's current UTC instant | Billing, Dispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENTIAL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ROUTE_NOT_PLANNING` | 409 Conflict |
| `ERR_VISIT_NOT_COMPLETED` | 409 Conflict |
| `ERR_CREW_OFFLINE` | 409 Conflict |
| `ERR_CREW_SKILL_MISSING` | 422 Unprocessable Entity |
| `ERR_BEFORE_PHOTO_REQUIRED` | 422 Unprocessable Entity |
| `ERR_AFTER_PHOTO_REQUIRED` | 422 Unprocessable Entity |
| `ERR_REGION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DATE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_VISIT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_NO_WEATHER_HOLD` | 409 Conflict |
| `ERR_ROUTE_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_NOT_MET` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_INVOICE` | 409 Conflict |
| `ERR_STALE_ROUTE_VERSION` | 412 Precondition Failed |
| `ERR_OPEN_VISITS_EXIST` | 409 Conflict |
| `ERR_EMPTY_ROUTE` | 422 Unprocessable Entity |
| `ERR_CREW_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
