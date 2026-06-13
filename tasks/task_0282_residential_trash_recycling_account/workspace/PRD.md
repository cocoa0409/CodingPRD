# Residential Trash & Recycling Account API — Product Requirements Document

## 1. Introduction

Municipal and private waste haulers need a single system of record that ties a resident's curbside service to the money that flows from it. A household signs up for a plan, receives a trash cart and a recycling cart, gets collected on a fixed weekday, occasionally requests a bulk pickup, sometimes has a pickup missed, sometimes contaminates the recycling stream, and pays a monthly bill — and every one of those events has a billing consequence. This API governs that whole arc, from provisioning a plan and a collection zone, through the day-to-day reporting of what happened at the curb, to the generation and settlement of period invoices.

The defining challenge of the domain is reconciliation. Credits earned from missed pickups, fees posted from contamination, surcharges for extra carts, and charges for on-request bulk pickups all converge on a forward-looking period invoice, and the order in which they are computed determines what the resident owes. The system therefore treats service lifecycle and billing lifecycle as two independent dimensions on the same account: a household that has stopped service may still owe money, and an actively-collected household may already be in collections. Schedules are temporally sensitive — holidays slip pickups, and the system must report the true effective date a crew will arrive without rippling that shift across the rest of the week.

This document specifies the entities, their parallel state machines, the calculation rules that derive every monetary figure, the validation order that guards each write, and the complete endpoint and error contract. Monetary amounts are integer cents throughout; there are no floating-point values anywhere in the system.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their operational capacity. The system recognizes exactly three roles: `Dispatcher`, `AccountHolder`, and `CrewLead`. A request missing either header, or carrying an `X-User-Role` that is not one of these three exact strings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the targeted operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`. The same holds for `CrewLead`: `X-User-ID` is an opaque field-crew identifier, recorded but never matched against an entity. When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `ServiceAccount`; ownership checks on any resource that references a `ServiceAccount` compare that resource's account foreign key to `X-User-ID`. A `Dispatcher` is operations staff and the broadest actor: it provisions plans, zones, accounts, and carts, drives the account service lifecycle, generates invoices, schedules and cancels extra pickups, waives contamination fees, and advances the test clock. An `AccountHolder` is the residential customer who manages their own payment method and autopay, pays and reads their invoices, requests and cancels extra pickups, and acknowledges contamination notices. A `CrewLead` is the field collection crew who reports pickup outcomes at the curb and completes scheduled extra pickups.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and a supplied value must be at least 1 and at most 100. The `offset` parameter sets how many items to skip from the front of the result; when omitted it defaults to 0, and a supplied value must be at least 0. A `limit` outside the inclusive range of 1 to 100, or a negative `offset`, is a malformed request rejected with `ERR_INVALID_REQUEST` (HTTP 422).

Unless an endpoint explicitly states another ordering, list results are sorted by `created_at` in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object, where `total_count` is the full count before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Most resources in this system are first-class records that carry a uniform set of system-managed fields. Each such resource exposes an `id` that is a server-minted UUID with no type prefix, a `created_at` and an `updated_at` that are ISO 8601 UTC timestamps with three fractional digits, and a `version` that is an integer beginning at 1 and incrementing by exactly one on every mutation of the resource. The `created_at` is fixed at creation; `updated_at` is refreshed on every change. This common shape applies to `ServicePlan`, `ServiceAccount`, `CollectionZone`, `CartAssignment`, `PickupSchedule`, `PickupEvent`, `ExtraPickupRequest`, `Invoice`, `Payment`, `MissedPickupCredit`, and `ContaminationNotice`.

The `Holiday` resource is the sole exception. A holiday entry is immutable after creation, so it carries only `id` and `created_at`; it has neither an `updated_at` nor a `version`.

Whenever an operation derives or refreshes a computed field on a resource — for example recomputing an account's balances — that counts as a mutation of the holding resource, refreshing its `updated_at` and incrementing its `version`, except where a specific workflow below states that a read-time recomputation does not itself bump the version.

### 2.5. Nested Resource Retrieval and Reference Integrity

Many paths address a resource nested beneath a parent, such as the carts under an account or the events under a pickup schedule. The server validates every path identifier left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that names no existing resource. A request for the events of a schedule that does not exist fails on the schedule before the events are ever considered.

Separately, when a write carries a foreign key in its body — a `plan_id`, a `zone_id`, an `invoice_id`, or any other reference to another resource — and that key names a resource that does not exist, the request is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404). Path-identifier existence (`ERR_NOT_FOUND`) and body-reference existence (`ERR_REFERENCE_NOT_FOUND`) are distinct concerns with distinct error identifiers.

### 2.6. Validation Order

When a single write could fail several checks, the system applies them in a fixed priority so that the returned error is deterministic. The order is: first authentication of the headers (`ERR_UNAUTHENTICATED`); then authorization of the role for the endpoint (`ERR_FORBIDDEN`); then existence of every path-referenced resource, left to right (`ERR_NOT_FOUND`); then existence of every body foreign key (`ERR_REFERENCE_NOT_FOUND`); then well-formedness of the body and query parameters — required fields present, enum members drawn from their allowed sets, integers within their declared ranges, and pagination bounds respected (`ERR_INVALID_REQUEST`); then, on the two optimistic-concurrency-guarded writes, the version check (`ERR_STALE_VERSION`); then the state-transition legality check that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`); and only after all of those, the endpoint's specific business rules. In other words, a body-shape problem surfaces before a stale-version problem, which surfaces before an illegal-state problem, which surfaces before any domain-specific conflict.

### 2.7. Money and Precision

Every monetary quantity in the system — base charges, surcharges, fees, credits, invoice totals, payment amounts, and account balances — is stored and exchanged as an integer number of cents. Because all calculation inputs are integer cents, every sum, difference, and product evaluates to an exact integer and no rounding is required or applied. There are no fractional-cent values and no floating-point representations anywhere in the contract.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded against acting on a stale view of a `ServiceAccount`, because both make decisions whose correctness depends on the account's exact current state. Each guarded write requires a non-optional `expected_account_version` field in its body carrying the client's last observed `version` of the target `ServiceAccount`. Before the operation proceeds, the server compares that value to the account's current `version`; if they differ, the write is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated.

Generating a period invoice for an account is the first such guarded write. Because a credit issuance, a contamination posting, or a cart change between the client's read and this write all advance the account's `version` and change the computed gross, an invoice request carrying an `expected_account_version` that no longer matches the account's current `version` is refused with `ERR_STALE_VERSION` rather than billing an outdated amount.

Transferring service out of an account is the second such guarded write. The transfer migrates issued credits and cancels the schedule, so if the account's state has shifted since the client read it — a credit issued, a suspension, an invoice generated — its `version` will have advanced and the transfer carrying a now-mismatched `expected_account_version` is refused with `ERR_STALE_VERSION`. No other endpoint takes a version field; all other writes proceed without an OCC check.

### 2.9. Hierarchical Consistency and Cascades

A great deal of this system's logic lives in cascades: a single write to one resource deliberately mutates others. Reporting a missed pickup issues a credit and changes the account's derived balances; voiding an invoice restores the credits it consumed; stopping an account expires its outstanding credits while transferring it preserves them. Each of these is specified in full in §3 alongside the workflow that triggers it. The governing rule is that every secondary effect is part of the same operation as its primary effect: when a cascade mutates a secondary resource, that resource's own `updated_at` and `version` advance as for any other mutation, and the originating resource's `version` advances as well where the workflow says so. The system's consistency model is immediate — all cascades complete within the triggering request, and a subsequent read reflects them.

## 3. Business Logic & Workflows

### 3.1. Provisioning: Plans, Zones, and Holiday Calendars

Service rests on two reference entities a `Dispatcher` sets up first. A **service plan** is created with a `tier` — one of `BASIC`, `STANDARD`, or `PREMIUM`, and required to be unique among plans that are not archived — together with the two cart sizes it provisions in gallons, `trash_cart_size_gallons` and `recycling_cart_size_gallons`, each of which must be exactly 35, 65, or 96. The plan also fixes its rate card: `monthly_base_cents` is the flat monthly service charge, `extra_cart_monthly_cents` is the monthly surcharge for each cart beyond the two a plan provisions, `extra_pickup_base_cents` is the flat charge for an on-request extra or bulk pickup before any per-item fees, and `bulk_item_cents` is the per-item charge for bulk items on such a pickup. Each of those four amounts must be zero or greater. A plan also carries an `archived` flag that begins as false; archiving a plan sets it to true. Archived plans are excluded from the default plan listing — they appear only when a list request opts in — and an archived plan can never be newly assigned to an account.

A **collection zone** is created with a human-readable `name`, a `base_pickup_weekday` giving the zone's normal weekday for collection as an integer from 0 through 6 where 0 is Monday and 6 is Sunday, and a `recycling_week_parity` of either `EVEN` or `ODD` that selects which alternating weeks recycling is collected, with the parity taken from the ISO week number. Because recycling runs every other week, only the weeks whose ISO week number matches the zone's parity carry a recycling pickup.

A zone owns a **holiday calendar**. A `Dispatcher` adds a holiday to a zone by supplying a `holiday_date` (a UTC-midnight date) and a `shift_direction` of either `DELAY_ONE_DAY` or `NONE`; the holiday records the owning zone through its `zone_id`. At most one holiday may exist for a given combination of `zone_id` and `holiday_date`. The holiday list for a zone is reachable by reverse lookup from the zone, exposing the entries whose `zone_id` is that zone. Holidays are immutable once written.

### 3.2. Opening an Account and Equipping It with Carts

A `Dispatcher` opens a residential **service account** by supplying the `plan_id` of the governing plan, the `zone_id` of the collection zone whose weekday and holiday calendar will drive the schedule, a `service_address`, and a `holder_name`. The address must be non-empty and must be unique among accounts whose `status` is `PENDING_START`, `ACTIVE`, or `SUSPENDED`; a collision against any such account is rejected with `ERR_ADDRESS_IN_USE` (HTTP 409). If the referenced plan is archived, the account cannot be created and the request is rejected with `ERR_PLAN_ARCHIVED` (HTTP 409). A freshly opened account begins with `status` of `PENDING_START`, a `billing_status` of `CURRENT`, `autopay_enabled` false, and a `stored_payment_token` of null; its `service_start_date` is null until service is activated, and its `transferred_from_account_id` is null because it is not the product of a transfer.

The account also exposes two derived monetary fields, `account_balance_cents` and `credit_balance_cents`, recomputed on every read of the account and after every mutation. The credit balance is the sum of `amount_cents` over every `MissedPickupCredit` on the account still in `ISSUED` status. The account balance is the sum of `amount_due_cents` over every `Invoice` on the account whose status is `OPEN` or `PAST_DUE`; the credit balance is deliberately not subtracted again at this point, because credit is already consumed at invoice generation and subtracting it here would double-count it. A read of the account that recomputes these derived figures does not by itself increment the account's `version`.

Carts are provisioned individually. A `Dispatcher` assigns a **cart** to an account by giving its `cart_type` — `TRASH` or `RECYCLING` — and its `size_gallons` of 35, 65, or 96. A cart's `account_id` ties it to its account, its `status` begins as `ACTIVE`, and removing a cart sets that `status` to `REMOVED`. Whether a cart is an extra is not supplied by the client but derived: a cart's `is_extra` flag is true when it is beyond the one `TRASH` and one `RECYCLING` cart a plan provisions. Each time a cart is assigned or removed, the `is_extra` flag is recomputed across that cart and its siblings on the same account so the surcharge picture stays accurate. An account's cart list is reachable by reverse lookup from the account.

### 3.3. Starting, Suspending, Resuming, and Stopping Service

The service lifecycle of an account is one of two independent dimensions tracked on the account; this dimension is its `status`, and it moves through `PENDING_START`, `ACTIVE`, `SUSPENDED`, and the two terminal states `STOPPED` and `TRANSFERRED_OUT`. Every transition below increments the account's `version` by one.

A `Dispatcher` activates service on a `PENDING_START` account, advancing it `PENDING_START → ACTIVE`. Three conditions must hold: the account is in `PENDING_START`, the account's plan is not archived, and the account is equipped with at least one `ACTIVE` cart of `cart_type` `TRASH` and at least one `ACTIVE` cart of `cart_type` `RECYCLING`. If either required cart is missing the activation is rejected with `ERR_CARTS_INCOMPLETE` (HTTP 409). On success the account's `service_start_date` is set to the current clock date, and the system generates the first run of `PickupSchedule` rows covering the next 28 days, derived from the zone's `base_pickup_weekday` for trash and from `base_pickup_weekday` combined with `recycling_week_parity` for recycling.

When an `ACTIVE` account is suspended it moves `ACTIVE → SUSPENDED`, and every `PLANNED` schedule row whose effective pickup date is on or after the current clock date is cancelled (its `status` becomes `CANCELLED`). Resuming a `SUSPENDED` account moves it `SUSPENDED → ACTIVE` and regenerates the `PLANNED` schedule rows for the next 28 days.

Stopping ends service permanently and is reachable from either `ACTIVE` or `SUSPENDED`, in both cases moving the account to `STOPPED`. Stopping cancels all `PLANNED` schedule rows, marks every `ACTIVE` cart `REMOVED`, and — this is the consequential cascade — expires every `ISSUED` `MissedPickupCredit` on the account by setting its `status` to `EXPIRED`; credit is forfeited when a household simply stops. (From `ACTIVE`, stopping additionally has the schedule rows to cancel; from `SUSPENDED`, the future schedule was already cancelled at suspension, so the stop need only remove carts and expire credits.) Each expired credit and removed cart is itself a mutation of that record.

### 3.4. Moving House: Transfer-Out

Transferring service is how a household carries its account to a new address rather than abandoning it. Reachable only from `ACTIVE`, a transfer moves the source account `ACTIVE → TRANSFERRED_OUT`. This is one of the two optimistic-concurrency-guarded writes (see §2.8): the request must carry `expected_account_version` matching the source account's current `version`, the destination plan named in the body must not be archived (otherwise `ERR_PLAN_ARCHIVED`), and the new address must satisfy the same uniqueness rule as account creation (otherwise `ERR_ADDRESS_IN_USE`). The body supplies `new_service_address`, `new_zone_id`, and an optional `new_plan_id`; when `new_plan_id` is omitted the destination inherits the source account's plan.

On success the system mints a new `ServiceAccount` in `PENDING_START` whose `transferred_from_account_id` points back at the source account. The destination copies the source's plan (or the supplied `new_plan_id`), `autopay_enabled`, and `stored_payment_token`. Critically, every `ISSUED` `MissedPickupCredit` on the source is migrated to the destination by re-pointing its `account_id` — unlike a stop, a transfer preserves credit across the move. As with a stop, the source account's `PLANNED` schedule rows are all cancelled and its `ACTIVE` carts are all marked `REMOVED`. Accounts may be listed with filters on `plan_id`, `zone_id`, and `transferred_from_account_id`, the last of which lets an operator trace the self-referential transfer chain from an old address to its successor.

### 3.5. Payment Method, Autopay, and Reading the Account

A payment method is attached to an account by storing an opaque `stored_payment_token`; this is available to both a `Dispatcher` and the owning `AccountHolder`, and setting it increments the account's `version`. Autopay is toggled separately by supplying `autopay_enabled`; when autopay is on, invoices auto-charge the stored method on their due date. Autopay cannot be enabled while the account has a null `stored_payment_token` — an attempt to do so is rejected with `ERR_NO_PAYMENT_METHOD` (HTTP 409). Toggling autopay increments the account's `version`. A single account record can be fetched directly, which is the canonical way to observe its recomputed `account_balance_cents` and `credit_balance_cents`.

### 3.6. The Pickup Schedule and the Holiday Shift

Each `PickupSchedule` row records the `account_id` it serves, the `stream` collected (`TRASH` or `RECYCLING`), and the planned `service_date` as a UTC-midnight date before any holiday adjustment. Its `status` begins `PLANNED` and can become `COMPLETED`, `MISSED`, or `CANCELLED`. The row also exposes a derived `effective_pickup_date`, which is the real date the crew is expected at the curb after applying the zone's holiday calendar.

The holiday shift is computed by an exact date match. For a given schedule row, the system looks for a holiday on the account's zone whose `holiday_date` equals the row's `service_date`. If such a holiday exists and its `shift_direction` is `DELAY_ONE_DAY`, the `effective_pickup_date` is the `service_date` advanced by exactly one day; if the holiday's `shift_direction` is `NONE`, or if no holiday falls on that date, the `effective_pickup_date` equals the `service_date` unchanged. Only the single pickup whose `service_date` lands exactly on the holiday slips — later pickups in the same week are never cascaded, so the shift is a one-day move with no ripple. This mapping is applied both when schedule rows are generated (at activation and on resume) and on every read of `effective_pickup_date`.

An account's schedule can be listed with optional `stream` and `status` filters. Unlike the default `created_at` ordering, this listing is ordered by `service_date` ascending and, within the same date, with `TRASH` before `RECYCLING`. A single schedule row can also be fetched directly.

### 3.7. Reporting Outcomes at the Curb

Only a `CrewLead` reports what happened at a pickup, and doing so creates a **pickup event** against the schedule row and fires the cascade appropriate to the outcome. The event carries the `schedule_id` of the planned pickup it reports against, an `outcome` of `COLLECTED`, `MISSED`, or `CONTAMINATED`, and a `reported_at` timestamp recording when the crew reported it. A report is only accepted while the schedule row is `PLANNED` and its parent account is `ACTIVE`; reporting against a row in any other state is an illegal transition. The `reported_at` instant must be at or after the schedule row's `effective_pickup_date` — a pickup cannot be reported before it was due — and an earlier timestamp is rejected with `ERR_REPORT_TOO_EARLY` (HTTP 409). A `CONTAMINATED` outcome may only be reported against a row whose `stream` is `RECYCLING`; reporting contamination on a trash row is rejected with `ERR_CONTAMINATION_NOT_RECYCLING` (HTTP 409). Every reported outcome increments the schedule row's `version`.

A `COLLECTED` outcome simply advances the row `PLANNED → COMPLETED`. A `MISSED` outcome advances the row `PLANNED → MISSED` and triggers the missed-pickup credit cascade described in §3.8. A `CONTAMINATED` outcome is special: the recycling is still hauled away, so the row still advances `PLANNED → COMPLETED`, but the system also opens a contamination notice as described in §3.9. The events recorded against a schedule row are reachable by reverse lookup from that row.

### 3.8. Missed-Pickup Credits

When a pickup is reported missed, the system issues a **missed-pickup credit** on the account, in `ISSUED` status, linking back to the originating event through its `pickup_event_id` and recording the `account_id` it benefits. The credit's `amount_cents` is computed at issuance and held. While `ISSUED`, the credit's `applied_invoice_id` is null; it is set to the consuming invoice when the credit is applied, at which point the credit's `status` becomes `APPLIED`. A credit may also reach `EXPIRED` when the account is stopped.

The credit amount turns on the stream and on the household's recent reliability history. The base credit is 300 cents for a missed `TRASH` pickup and 200 cents for a missed `RECYCLING` pickup. The system then counts the prior misses on the account — the number of `MissedPickupCredit` rows whose status is `ISSUED` or `APPLIED` and whose originating event's `reported_at` falls within the rolling 90-day window that excludes the instant exactly 90 days before the current clock time and includes the current clock instant. If that count of prior misses is strictly greater than 2, the household is a repeat victim and an extra 150 cents is added to the base credit; otherwise the credit is exactly the base. Issuing a credit raises the account's `credit_balance_cents` and re-derives its `account_balance_cents` immediately. An account's credits are reachable by reverse lookup from the account, and credits can also be listed across the system filtered by `pickup_event_id` or by `applied_invoice_id`, with a single credit fetchable directly.

### 3.9. Contamination Notices

A `CONTAMINATED` recycling outcome opens a **contamination notice** in `OPEN` status, linking to the triggering event by `pickup_event_id` and recording the `account_id`. The crew reports the `severity` as `MINOR` or `MAJOR`, and the system computes a `fee_cents` at issuance. The fee depends on how many notices the account has seen before: the system counts the `ContaminationNotice` rows on the account whose status is `OPEN`, `ACKNOWLEDGED`, or `WAIVED` that were created strictly before this one. If that prior count is zero — this is the account's first contamination notice ever — the fee is 0 cents, a free warning. Otherwise the fee is 1500 cents for a `MINOR` notice, and for a `MAJOR` notice it is 1500 cents multiplied by 2, i.e. 3000 cents. A non-waived notice's fee posts to the account's next period invoice gross.

The owning `AccountHolder` may acknowledge an `OPEN` notice, moving it `OPEN → ACKNOWLEDGED`; acknowledgement is a record-keeping step that leaves the fee in place. A `Dispatcher` may waive a notice from either `OPEN` or `ACKNOWLEDGED`, moving it to the terminal `WAIVED` state; waiving sets `fee_cents` to 0, which reverses the posting to the next invoice gross. Each of these transitions increments the notice's `version`. An account's notices are reachable by reverse lookup from the account, notices can be listed across the system filtered by `pickup_event_id`, and a single notice can be fetched directly.

### 3.10. Extra and Bulk Pickups

A household — or a `Dispatcher` acting for it — requests an **extra pickup** on the account by supplying a `requested_date` (UTC midnight) and a `bulk_item_count` of zero or more. The request records its `account_id`, begins in `REQUESTED` status, and carries a `charge_cents` that is not yet meaningful until the request is scheduled. The request lifecycle runs `REQUESTED`, `SCHEDULED`, and the terminal `COMPLETED` and `CANCELLED`. Every transition increments the request's `version`.

A `Dispatcher` schedules a `REQUESTED` request, advancing it `REQUESTED → SCHEDULED`, but only when the parent account is `ACTIVE` and no other `SCHEDULED` extra-pickup request on the same account already holds the same `requested_date`; a same-day collision is rejected with `ERR_DATE_DOUBLE_BOOKED` (HTTP 409). Scheduling freezes the `charge_cents` and creates a `PLANNED` `PickupSchedule` row for the requested date on the `TRASH` stream, flagged as an extra. The frozen charge is computed from the account's plan and the request's `bulk_item_count`: it starts from the plan's `extra_pickup_base_cents`. If `bulk_item_count` is zero, the charge is exactly that base. If `bulk_item_count` is between 1 and 2 inclusive, the charge is still exactly the base, because the first two bulk items are included in the base at no extra cost. If `bulk_item_count` exceeds 2, the billable item count is `bulk_item_count` minus 2, and the charge is the base plus that billable count multiplied by the plan's `bulk_item_cents`.

A `CrewLead` completes a `SCHEDULED` request, moving it `SCHEDULED → COMPLETED`. A request may be cancelled by a `Dispatcher` or the owning `AccountHolder`: cancelling from `REQUESTED` simply moves it `REQUESTED → CANCELLED` with no further effect, while cancelling from `SCHEDULED` moves it `SCHEDULED → CANCELLED`, cancels the linked `PickupSchedule` row, and resets `charge_cents` to 0 so the period invoice bills nothing for it. This is the same plan and the same request inputs as a scheduled charge, yet the result diverges entirely by context — a scheduled request carries its full computed charge into billing, a cancelled one carries zero. An account's extra-pickup requests are reachable by reverse lookup from the account, and a single request is fetchable directly.

### 3.11. Period Invoicing and the Gross Calculation

A `Dispatcher` generates a period **invoice** for an account, which is the second optimistic-concurrency-guarded write (see §2.8): the body carries `expected_account_version`, `period_start`, `period_end`, and `due_date`, where `period_start` is the inclusive start of the billing period and `period_end` is its exclusive end (both UTC midnight). The new invoice records its `account_id`, begins in `OPEN` status, and computes three derived monetary figures in a pinned order.

First the **gross** (`gross_amount_cents`) is built from four parts summed together. Part one is the plan's `monthly_base_cents`. Part two is the extra-cart surcharge: take the count of `ACTIVE` carts on the account, subtract the two carts every plan provisions (one `TRASH` plus one `RECYCLING`), floor that difference at zero, and multiply by the plan's `extra_cart_monthly_cents`. Part three is the sum of `charge_cents` over every `ExtraPickupRequest` on the account whose status is `SCHEDULED` or `COMPLETED` and whose `requested_date` falls on or after `period_start` and strictly before `period_end`. Part four is the sum of `fee_cents` over every `ContaminationNotice` on the account whose status is `OPEN` or `ACKNOWLEDGED` and whose linked recycling pickup — traced from the notice through its event to that event's schedule row — has a `service_date` on or after `period_start` and strictly before `period_end`. The gross is the sum of these four parts.

Second, **credit application** (`credit_applied_cents`) is computed after the gross and frozen onto the invoice. The amount applied is the smaller of the gross and the account's current `credit_balance_cents`. The system consumes `ISSUED` `MissedPickupCredit` rows oldest-first by `created_at` ascending — and where two credits share an identical `created_at`, the one with the smaller `amount_cents` first — marking each consumed credit `APPLIED` and setting its `applied_invoice_id` to this invoice, until the applied total reaches the computed amount. Third, the **amount due** (`amount_due_cents`) is the gross minus the credit applied, floored at zero so it never goes negative. Generating the invoice increments the account's `version`.

Credit application is a snapshot taken at generation. An invoice generated and left `OPEN` reflects only the credit that was `ISSUED` at generation time; credits issued later do not retroactively reduce an already-generated invoice. The complementary case is a voided invoice (see §3.12): voiding releases the credit it had consumed back to `ISSUED`, so re-billing the same account for the same period can yield a different `amount_due_cents` if credits or contamination changed in between. An account's invoices are reachable by reverse lookup from the account, and a single invoice is fetchable directly.

### 3.12. Paying and Voiding Invoices

An invoice is paid by the owning `AccountHolder` or a `Dispatcher`, who submits a payment giving the settling `invoice_id`, the `amount_cents` tendered, and the `method` of `MANUAL` or `AUTOPAY`. Settlement is exact-only: the payment's `amount_cents` must equal the invoice's `amount_due_cents`, and any other amount — too little or too much — is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). Payment is allowed against an invoice in either `OPEN` or `PAST_DUE` status, advancing it to `PAID` in both cases. A payment creates a **payment** record whose `status` is always `APPLIED`; payments are append-only and settle on creation, so `APPLIED` is their only state. Paying an invoice increments its `version`, and the system then re-evaluates the account's `billing_status`: when no `OPEN` or `PAST_DUE` invoice remains on the account, the billing dimension returns to `CURRENT`. The payments against an invoice are reachable by reverse lookup from that invoice.

A `Dispatcher` may void an `OPEN` invoice, advancing it `OPEN → VOID`. Voiding restores any `MissedPickupCredit` this invoice had consumed back to `ISSUED` — re-pointing each such credit's `applied_invoice_id` to null — so the account's `credit_balance_cents` is conserved across the void. Voiding increments the invoice's `version`.

### 3.13. The Billing Dimension and the Clock

Separately from the service lifecycle, every account carries a billing dimension in `billing_status`, which begins `CURRENT` and moves among `CURRENT`, `PAST_DUE`, and `IN_COLLECTIONS` independently of the service `status`; a `STOPPED` account can still be `PAST_DUE`, and an `ACTIVE` account can be `IN_COLLECTIONS`. These transitions are system-driven and evaluated when the clock is advanced.

An administrative test-driving capability lets a `Dispatcher` set the server's logical clock to a supplied `to_iso8601` instant; the response reports the new `current_utc` and the count of `accounts_advanced`. Advancing the clock evaluates the billing machine on every account. An account moves `CURRENT → PAST_DUE` when it has an `OPEN` invoice whose `due_date` is strictly before the new clock date, and that invoice's own `status` is set to `PAST_DUE` as part of the same transition. An account moves `PAST_DUE → IN_COLLECTIONS` when it holds an invoice that is `PAST_DUE` and for which the clock date minus the invoice's `due_date` is strictly more than 60 days. From either `PAST_DUE` or `IN_COLLECTIONS`, the account returns to `CURRENT` once no invoice on it remains `OPEN` or `PAST_DUE` — the same settlement-driven return described for payment in §3.12. Every billing-dimension transition increments the account's `version`.

## 4. Endpoint Definitions

Operations that create a new, standalone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including lifecycle transitions and toggles that mutate a resource in place — return `200 OK`. All list and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/service-plans` | Create a service plan | Dispatcher |
| GET | `/service-plans` | List service plans (archived excluded unless `include_archived=true`) | Dispatcher, AccountHolder |
| GET | `/service-plans/{id}` | Fetch one service plan | Dispatcher, AccountHolder |
| POST | `/service-plans/{id}/archive` | Archive (soft-delete) a plan | Dispatcher |
| POST | `/collection-zones` | Create a collection zone | Dispatcher |
| GET | `/collection-zones/{id}` | Fetch one collection zone | Dispatcher, AccountHolder |
| POST | `/collection-zones/{id}/holidays` | Add a holiday to a zone's calendar | Dispatcher |
| GET | `/collection-zones/{id}/holidays` | List holidays for a zone | Dispatcher, AccountHolder |
| POST | `/accounts` | Create a residential service account | Dispatcher |
| GET | `/accounts` | List accounts (filterable by `plan_id`, `zone_id`, `transferred_from_account_id`) | Dispatcher |
| GET | `/accounts/{id}` | Fetch one account (recomputes balances) | Dispatcher, AccountHolder |
| POST | `/accounts/{id}/carts` | Assign a cart to an account | Dispatcher |
| GET | `/accounts/{id}/carts` | List an account's carts | Dispatcher, AccountHolder |
| POST | `/carts/{id}/remove` | Remove (deactivate) a cart | Dispatcher |
| POST | `/accounts/{id}/activate-start` | Activate a PENDING_START account | Dispatcher |
| POST | `/accounts/{id}/suspend` | Suspend an ACTIVE account | Dispatcher |
| POST | `/accounts/{id}/resume` | Resume a SUSPENDED account | Dispatcher |
| POST | `/accounts/{id}/stop` | Stop service permanently | Dispatcher |
| POST | `/accounts/{id}/transfer-out` | Transfer service to a new address (OCC-guarded) | Dispatcher |
| POST | `/accounts/{id}/payment-method` | Attach a tokenized payment method | Dispatcher, AccountHolder |
| POST | `/accounts/{id}/autopay` | Enable or disable autopay | Dispatcher, AccountHolder |
| POST | `/accounts/{id}/invoices` | Generate a billing-period invoice (OCC-guarded) | Dispatcher |
| GET | `/accounts/{id}/invoices` | List an account's invoices | Dispatcher, AccountHolder |
| GET | `/invoices/{id}` | Fetch one invoice | Dispatcher, AccountHolder |
| POST | `/invoices/{id}/pay` | Pay an OPEN or PAST_DUE invoice | AccountHolder, Dispatcher |
| POST | `/invoices/{id}/void` | Void an OPEN invoice | Dispatcher |
| GET | `/invoices/{id}/payments` | List payments against an invoice | Dispatcher, AccountHolder |
| GET | `/accounts/{id}/pickup-schedules` | List an account's pickup schedule rows (filterable by `stream`, `status`) | Dispatcher, AccountHolder |
| GET | `/pickup-schedules/{id}` | Fetch one pickup schedule row | Dispatcher, AccountHolder, CrewLead |
| POST | `/pickup-schedules/{id}/events` | Report a pickup outcome | CrewLead |
| GET | `/pickup-schedules/{id}/events` | List events for a schedule row | Dispatcher, AccountHolder, CrewLead |
| POST | `/accounts/{id}/extra-pickups` | Create an extra/bulk pickup request | AccountHolder, Dispatcher |
| GET | `/accounts/{id}/extra-pickups` | List an account's extra-pickup requests | Dispatcher, AccountHolder |
| GET | `/extra-pickups/{id}` | Fetch one extra-pickup request | Dispatcher, AccountHolder |
| POST | `/extra-pickups/{id}/schedule` | Schedule a REQUESTED extra pickup | Dispatcher |
| POST | `/extra-pickups/{id}/complete` | Complete a SCHEDULED extra pickup | CrewLead |
| POST | `/extra-pickups/{id}/cancel` | Cancel a REQUESTED or SCHEDULED extra pickup | Dispatcher, AccountHolder |
| GET | `/accounts/{id}/credits` | List an account's missed-pickup credits | Dispatcher, AccountHolder |
| GET | `/credits` | List credits (filterable by `pickup_event_id`, `applied_invoice_id`) | Dispatcher, AccountHolder |
| GET | `/credits/{id}` | Fetch one missed-pickup credit | Dispatcher, AccountHolder |
| GET | `/accounts/{id}/contamination-notices` | List an account's contamination notices | Dispatcher, AccountHolder |
| GET | `/contamination-notices` | List contamination notices (filterable by `pickup_event_id`) | Dispatcher, AccountHolder |
| GET | `/contamination-notices/{id}` | Fetch one contamination notice | Dispatcher, AccountHolder |
| POST | `/contamination-notices/{id}/acknowledge` | Acknowledge a contamination notice | AccountHolder |
| POST | `/contamination-notices/{id}/waive` | Waive a contamination notice's fee | Dispatcher |
| POST | `/_clock/set_current_utc` | Set the server clock; evaluate billing transitions | Dispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CARTS_INCOMPLETE` | 409 |
| `ERR_PLAN_ARCHIVED` | 409 |
| `ERR_ADDRESS_IN_USE` | 409 |
| `ERR_DATE_DOUBLE_BOOKED` | 409 |
| `ERR_REPORT_TOO_EARLY` | 409 |
| `ERR_CONTAMINATION_NOT_RECYCLING` | 409 |
| `ERR_NO_PAYMENT_METHOD` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
