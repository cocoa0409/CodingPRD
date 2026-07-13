# Community Garden & Plot Allocation API — Product Requirements Document

## 1. Introduction

Community garden sites live and die by the fairness of how a scarce resource — a fixed pool of cultivable plots — is handed out among more applicants than there are beds. This document specifies the backend service that runs a garden's full allocation lifecycle: cataloguing plots and their size classes, maintaining a waitlist of applicants ranked by tenure and standing, extending time-boxed offers, minting seasonal assignments, and settling the seasonal fees that keep the site solvent.

The service is deliberately opinionated about **who** may do **what**. A `GardenManager` operates the physical inventory and adjudicates conduct; a `Treasurer` — and only a `Treasurer` — touches money; a `Gardener` acts on their own applications, assignments, and bookings and nothing else. This separation of duties is not cosmetic: it exists so that the same person cannot both assess a penalty and forgive the fee attached to it. Alongside allocation, the system meters seasonal water consumption, enforces a per-season work-hour contribution, tracks rule and abandonment violations through a graduated compliance process, and manages the shared tool shed that every active gardener draws from.

Every deadline, offer window, cure period, and overlap check in this system is evaluated against a **logical clock** that the operator advances explicitly, never against wall-clock time. This makes the whole workflow deterministic and testable: an offer expires, a cure period lapses, or a tool comes back late strictly because the clock was moved past the relevant instant.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming their role. If either header is missing, or `X-User-Role` is not one of the three roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation — or a gardener attempts to act on a resource they do not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The three roles are spelled exactly `Gardener`, `GardenManager`, and `Treasurer`.

When `X-User-Role` is `Gardener`, `X-User-ID` is the `id` of the acting `Gardener` entity. Ownership checks on any resource that references a gardener compare that resource's `gardener_id` to `X-User-ID`: a gardener may accept or decline only their own application, request renewal only on an assignment whose `gardener_id` is theirs, and may only file work logs, water readings, tool loans, and shed bookings under their own gardener identity.

When `X-User-Role` is `GardenManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts it for authentication and authorization but never compares it to any entity's `id`. When `X-User-Role` is `Treasurer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity and is never compared to an entity `id`. Both operator roles are authorized purely by role membership, not by ownership.

The `GardenManager` operates inventory and allocation: managing the logical clock, creating gardens, plots, gardeners, and tools, running offers and direct assignments, confirming renewals, settling and forfeiting assignments, and driving the compliance process. The `Treasurer` is confined to the money axis — recording payments, waiving fees, and issuing refunds. A `Gardener` submits and answers applications, requests renewals, and records their own work, water, tool, and shed activity. All three roles may perform every read (`GET`) in the system.

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

All list endpoints are paginated through two query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, must be at least 1, and may not exceed 100. `offset` defaults to 0 and must be at least 0. Results are always returned sorted by `created_at` in ascending order (oldest first).

For list responses, the `meta` object additionally carries `limit`, `offset`, `total_count` (the total number of matching rows before pagination), and `has_more` (true when rows remain beyond the current window).

### 2.4. Common Resource Properties, Versioning, and the Logical Clock

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix, and a `created_at` timestamp. Most resources — gardens, plots, gardeners, applications, assignments, compliance cases, tools, and tool loans — additionally carry an `updated_at` timestamp and an integer `version`. Whenever such a resource is mutated, its `updated_at` is refreshed to the current logical-clock instant and its `version` increments by one. Three resource types are lighter-weight records: work logs, water readings, and shed bookings expose only `id` and `created_at` — they have neither an `updated_at` nor a `version` field, because once written they are never mutated.

All timestamps are ISO 8601 UTC values rendered with three fractional-second digits. The system does not read the host wall clock for any business decision. Instead it maintains a **logical clock**, and an operator advances it by supplying a target instant as `to_iso8601`. The startup default for the logical clock is exactly `2026-03-01T00:00:00Z`; before any clock-setting call is made, every deadline, expiry, and window comparison reads that default value rather than real time. Season boundaries, offer windows, cure deadlines, tool-loan intervals, and shed-booking intervals are all evaluated against whatever instant the logical clock currently holds.

### 2.5. Optimistic Concurrency on Direct Plot Assignment

A direct manager assignment is the one write in the system guarded by optimistic concurrency. A request to directly assign a plot must carry `expected_plot_version`, a non-optional field holding the `version` of the target plot as the client last observed it. If `expected_plot_version` does not equal the plot's current `version`, the assignment is rejected with `ERR_STALE_VERSION` (HTTP 412). The intent is precise: between the manager reading the plot and issuing the assign, the plot may have been offered to and reserved by a waitlisted applicant — a legitimate supersede that advances the plot's `version` — and in that case the manager's now-stale request must not silently overwrite the reservation. No other endpoint accepts or requires a version field.

### 2.6. Monetary Amounts, Precision, and the Fee Ledger

Every monetary amount in the system — fees, deposits, penalties, fines, and balances — is expressed as an integer number of cents; there are no fractional-cent values in storage or in responses. Wherever a calculation multiplies by a fractional quantity (a fractional work-hour shortfall, or a per-gallon water rate), the product is rounded to the nearest whole cent using round-half-up (a value exactly at the halfway point rounds up).

Each gardener carries a running fee ledger in `balance_owed_cents`, a signed integer. Creating an assignment adds its provisional fee to the leaseholder's `balance_owed_cents`; settling or forfeiting reconciles the difference between the final and provisional fee; paying subtracts the paid amount; waiving subtracts the outstanding amount; and refunding adds the refunded amount back. This ledger is conserved: a payment of some amount immediately followed by a refund of that same amount leaves `balance_owed_cents` exactly at its pre-payment value, with no drift. A refund is therefore a true compensating entry that reverses the ledger effect of the payment it reverses.

### 2.7. The Plot Pool Invariant

Within any one garden the plot pool is a conserved quantity. A garden's `total_plots` always equals the number of `Plot` rows whose `garden_id` is that garden's `id`, and that same total always equals the sum of plots in the `AVAILABLE`, `RESERVED`, and `ASSIGNED` states. `available_plot_count` is the running count of that garden's plots currently in `AVAILABLE`. These counts are exact integers maintained across every plot-status transition. A subtle consequence appears at forfeiture: when a forfeited plot moves from `ASSIGNED` back to `AVAILABLE` and, in the same operation, is immediately re-offered and moves on to `RESERVED`, the net count of `AVAILABLE` plots is left unchanged.

### 2.8. Validation Ordering and Nested Path Resolution

When several conditions could reject one request, they are evaluated in a fixed priority order and the first failure is the one returned. Authentication comes first: a missing or unknown-role request fails with `ERR_UNAUTHENTICATED` before anything else is examined. Authorization is next — role permission and, for gardener-owned actions, the ownership match between `X-User-ID` and the resource's `gardener_id` — failing with `ERR_UNAUTHORIZED`. Existence checks follow, resolving every referenced entity and returning the appropriate not-found error (for example `ERR_GARDEN_NOT_FOUND`, `ERR_PLOT_NOT_FOUND`, `ERR_GARDENER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_COMPLIANCE_CASE_NOT_FOUND`, `ERR_TOOL_NOT_FOUND`, or `ERR_TOOL_LOAN_NOT_FOUND`, each HTTP 404). Body shape and type validation (`ERR_VALIDATION`, HTTP 422) comes after existence. Only once a request has passed authentication, authorization, existence, and shape validation are the domain-specific state, concurrency, safety, referential, constraint, fiscal, and temporal rules described throughout §3 applied, roughly in that order of precedence; the concurrency version check on a direct assignment, for instance, is evaluated after the plot's availability state but the specific ordering details are called out with each workflow below.

For nested read paths, path parameters are resolved left to right. A request such as listing an assignment's work logs first resolves the assignment `id` in the path (returning `ERR_ASSIGNMENT_NOT_FOUND` if it does not exist) before returning the nested collection; a request scoped to a garden resolves the garden `id` first (returning `ERR_GARDEN_NOT_FOUND` when absent).

## 3. Business Logic & Workflows

### 3.1. Standing Up a Garden Site

A `GardenManager` bootstraps a site by registering a garden. The creation payload supplies the site's `name`, a human-readable `season_label` such as "2026-SPRING", and the season window as `season_start` (the inclusive start instant) and `season_end` (the exclusive end instant). The manager may optionally supply `offer_window_days`, the number of days an offered application has to accept before it lapses; when omitted this defaults to 7, and it must be at least 1. A newly created garden begins with `total_plots` and `available_plot_count` both at zero — these are computed roll-ups the system maintains, never client input.

Plots are added to a garden one at a time. Each plot carries the `garden_id` of its owning garden, a `label` that is meaningful within that garden such as "A-12", and a `size` drawn from the three size classes `SMALL`, `MEDIUM`, and `LARGE`. Size is consequential: it drives the seasonal fee, the water allowance, and the work-hour requirement. A plot starts life in `AVAILABLE` status — the `status` field ranges over `AVAILABLE`, `RESERVED`, and `ASSIGNED` — and its `current_assignment_id` (a denormalized pointer to the assignment presently occupying it) is null until a plot is assigned. Adding a plot increments the owning garden's `total_plots` and, because the new plot is available, its `available_plot_count` as well.

Gardeners register with a `full_name` and an `email`. The email must be unique across all gardeners; a second registration reusing an existing address is rejected with `ERR_DUPLICATE_EMAIL` (HTTP 409). A freshly registered gardener starts with `tenure_seasons` at 0, `standing` of `GOOD` (the standing field ranges over `GOOD`, `PROBATION`, and `SUSPENDED`), `strike_count` at 0, and `balance_owed_cents` at 0.

A garden's shed is stocked with shared tools. Each tool records the `garden_id` of the garden whose shed holds it, a `name` such as "Wheelbarrow #2", and a `category` of `HAND`, `POWER`, or `CART`. A tool also carries `cleaning_buffer_hours`, the downtime appended after each loan's effective end before the tool may be re-loaned; this defaults to 4 hours and cannot be negative. The tools of a garden can be listed, optionally filtered by `category`, through the garden's tool collection.

### 3.2. Joining the Waitlist and How Priority Is Scored

A `Gardener` joins a garden's waitlist by submitting an application naming their `gardener_id`, the `garden_id` they want in, and the `requested_size` they are waiting for (`SMALL`, `MEDIUM`, or `LARGE`). An application's `status` moves through `SUBMITTED`, `WAITLISTED`, `OFFERED`, `ACCEPTED`, `DECLINED`, and `EXPIRED`; on submission the system immediately advances a new application from `SUBMITTED` to `WAITLISTED`. A gardener may not hold two live bids on the same shelf: if the same gardener already has an application for the identical combination of `gardener_id`, `garden_id`, and `requested_size` that is currently `WAITLISTED` or `OFFERED`, the new submission is rejected with `ERR_DUPLICATE_APPLICATION` (HTTP 409).

Priority determines who is offered a freed plot first, and it is computed from the applicant's own standing. A gardener's **renewal priority score** is their `tenure_seasons` multiplied by a tenure weight of 10, plus a standing bonus that is 5 when their `standing` is `GOOD`, 0 when `PROBATION`, and negative 100 when `SUSPENDED`, minus their `strike_count` multiplied by a strike weight of 3. The result is an integer score.

This score is computed in two variants that can diverge. At the moment an application is submitted, the system freezes a snapshot of the score into `priority_score_at_submission`, using the gardener's `tenure_seasons`, `standing`, and `strike_count` as they stood at submission time. Later, when a plot is actually being offered, the score is recomputed live from each candidate gardener's **current** `tenure_seasons`, `standing`, and `strike_count` — which may have changed since submission because the gardener renewed another lease (raising tenure) or drew a compliance strike (changing standing and strike count). The live recomputation, not the frozen snapshot, is what ranks candidates when a plot is offered; the snapshot is retained on the application as the value observed at submission.

Applications can be read individually and listed with filters on `gardener_id`, `garden_id`, `status`, and `requested_size`.

### 3.3. Allocating a Plot: Offers, Acceptance, and Release

When a `GardenManager` offers an `AVAILABLE` plot, the server itself picks the recipient. It assembles the candidate set of applications that are `WAITLISTED`, belong to the plot's garden, and whose `requested_size` equals the plot's `size`, then ranks them by renewal priority score computed live (the as-of-allocation variant) in descending order, breaking ties by the application's `created_at` ascending — never by `id`. The top-ranked candidate is selected. If no candidate exists, the offer is rejected with `ERR_NO_ELIGIBLE_APPLICANT` (HTTP 409). The plot must be `AVAILABLE` to be offered; offering a plot whose `status` is anything else fails with `ERR_PLOT_NOT_AVAILABLE` (HTTP 409). The `requested_size` of the selected application must equal the plot's `size`; a mismatch surfaces as `ERR_SIZE_MISMATCH` (HTTP 409). A successful offer advances the plot from `AVAILABLE` to `RESERVED` and increments the plot's `version` by one, and moves the selected application from `WAITLISTED` to `OFFERED`, setting its `offered_plot_id` to the plot and its `offer_expires_at` to the current clock plus the garden's `offer_window_days`.

The offered gardener responds by accepting or declining, and only the gardener who owns the application may do so. Both actions require the application to be in `OFFERED`; acting on an application in any other status fails with `ERR_OFFER_NOT_PENDING` (HTTP 409). Acceptance additionally requires that the clock has not passed the application's `offer_expires_at`; accepting at or before that instant is allowed, but accepting after it is rejected with `ERR_OFFER_EXPIRED` (HTTP 409). Because acceptance re-checks the pairing, the plot named by `offered_plot_id` must still be `RESERVED`, and the application's `requested_size` must still equal the plot's `size` (`ERR_SIZE_MISMATCH` otherwise). A valid acceptance moves the application from `OFFERED` to `ACCEPTED`, advances the plot from `RESERVED` to `ASSIGNED` (incrementing the plot's `version`), and creates a new `Assignment` linked through its `application_id` to the accepted application. The assignment is born with `occupancy_status` of `ACTIVE` and `fee_status` of `UNPAID`; its `provisional_fee_cents` is computed at creation and added to the gardener's `balance_owed_cents`, and the plot's `current_assignment_id` is pointed at the new assignment.

Declining moves the application from `OFFERED` to `DECLINED`, returns the plot from `RESERVED` to `AVAILABLE` (incrementing the plot's `version`), and clears the application's `offered_plot_id` and `offer_expires_at`.

Offers do not linger. A `GardenManager` may run an expiry sweep over a garden, which finds every application still `OFFERED` whose `offer_expires_at` is strictly before the current clock and expires each one: the application moves from `OFFERED` to `EXPIRED`, its held plot returns from `RESERVED` to `AVAILABLE` with the plot's `version` incremented, and its `offered_plot_id` and `offer_expires_at` are cleared. The sweep returns the collection of applications it expired.

### 3.4. Direct Manager Assignment and Season Conflicts

Beyond the waitlist path, a `GardenManager` may directly assign an `AVAILABLE` plot to a specific gardener, superseding any pending offer selection. The request names the `gardener_id` of the intended leaseholder and carries `expected_plot_version` for the optimistic-concurrency check described in §2.5. The plot must be `AVAILABLE` (`ERR_PLOT_NOT_AVAILABLE` otherwise), and `expected_plot_version` must match the plot's current `version` or the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The assignment must also not double-book the season: if any non-terminal assignment already exists on this plot whose leased interval from `season_start` (inclusive) to `season_end` (exclusive) overlaps the garden's current season, the request fails with `ERR_PLOT_SEASON_CONFLICT` (HTTP 409). Intervals that merely touch at a boundary — one season's exclusive end equal to another's inclusive start — do not overlap and are permitted; the comparison is half-open with no buffer.

A successful direct assignment creates an `Assignment` with `occupancy_status` `ACTIVE` and `fee_status` `UNPAID` and no `application_id` (it did not arise from an application), computes its `provisional_fee_cents`, adds that to the gardener's `balance_owed_cents`, advances the plot from `AVAILABLE` to `ASSIGNED`, sets the plot's `current_assignment_id`, and increments the plot's `version`. Each assignment also snapshots its own `plot_id`, `gardener_id`, `garden_id`, `size`, and the `season_start` and `season_end` copied from the garden at creation; the `size` snapshot, not the plot's live size, drives that assignment's fee and requirements thereafter.

### 3.5. Seasonal Obligations: Work Hours and Water Metering

Holding a plot for a season carries a labor obligation. Each assignment has a `required_work_hours` derived from its `size`: a `SMALL` plot requires 8 hours, a `MEDIUM` plot 12 hours, and a `LARGE` plot 16 hours. A gardener discharges the obligation by filing work logs against their assignment. A work log names the `assignment_id` it credits, the `hours` contributed (which must be strictly greater than zero), the instant the work was performed as `logged_on`, and an optional `note`. Each accepted work log adds its `hours` to the assignment's running `logged_work_hours` tally. Work logs for an assignment can be listed back through the assignment's work-log collection.

Water is metered per billing period. A season is divided into 3 billing periods, and a gardener records consumption by filing a water reading naming the `assignment_id` it meters, the `period_index` of the period (an integer from 1 through 3), the `gallons_used` during that period (which must be zero or greater), and the instant the meter was read as `recorded_on`. At most one reading may exist for a given assignment and period: a second reading for the same `assignment_id` and `period_index` is rejected during body validation with `ERR_VALIDATION` (HTTP 422), the same code that rejects a missing field, a bad enum, or an out-of-range value such as a `period_index` outside 1 through 3 or a negative `gallons_used`. An assignment's water readings can be listed through its water-reading collection.

### 3.6. Fees, Settlement, and the Money Axis

Every assignment carries two independent status axes. The `occupancy_status` axis tracks physical tenancy and ranges over `ACTIVE`, `RENEWAL_PENDING`, `RENEWED`, `ENDED`, and `FORFEITED`. The `fee_status` axis tracks money and ranges over `UNPAID`, `PAID`, `WAIVED`, and `REFUNDED`. The two move independently: an assignment can be settled on the occupancy axis while still `UNPAID`, or paid while still `ACTIVE`.

The seasonal fee is computed in two variants keyed by the assignment's `size`. At creation, only the **provisional** fee is known, and it is a flat estimate: a size-based base fee plus a refundable water deposit. The base fee is 3000 cents for a `SMALL` plot, 5000 for `MEDIUM`, and 8000 for `LARGE`; the water deposit is 500 cents for `SMALL`, 1000 for `MEDIUM`, and 1500 for `LARGE`. The `provisional_fee_cents` stored at creation is simply the base fee plus the deposit for that size, ignoring actual water usage and work hours entirely.

When an assignment is closed, the **final** fee reconciles actual usage and is written to `final_fee_cents` (which is null until close). The final fee starts from the same size-based base fee, adds the season's water overage charge, adds a work-hour shortfall penalty, and then subtracts the water deposit — with the whole result floored at zero. Concretely: the water overage charge and the work-shortfall penalty are each fully resolved first, then combined as base plus water overage plus work penalty minus deposit, and only then is the outer floor applied so the final fee is never negative. The work-hour shortfall penalty is computed from the shortfall hours, which is the greater of zero and the assignment's `required_work_hours` minus its accumulated `logged_work_hours`; that shortfall is multiplied by a penalty rate of 1500 cents per hour and rounded half-up to whole cents. A gardener who met or exceeded the requirement has a zero shortfall and no penalty.

The season's water overage charge is an aggregation across the 3 billing periods, and the order of rounding is significant. For each period from 1 through 3, the system reads that period's water reading for the assignment — a period with no reading contributes zero gallons — and computes the period's overage gallons as the greater of zero and `gallons_used` minus the free allowance for the plot's size. The free allowance is 100 gallons per period for a `SMALL` plot, 200 for `MEDIUM`, and 350 for `LARGE`. Each period's overage gallons are multiplied by the water rate of 3.5 cents per gallon and that per-period charge is rounded half-up to whole cents **before** it is added to the running total. The season's water overage charge is the integer sum of those already-rounded per-period charges. Rounding each period first and then summing is the pinned order; summing raw overage gallons across all periods and rounding once at the end would yield a different, incorrect figure.

Settling and forfeiting both close occupancy and both compute the final fee, but they differ in what happens to the freed plot. Settling — permitted only when `occupancy_status` is `ACTIVE` or `RENEWAL_PENDING`, otherwise `ERR_ASSIGNMENT_NOT_ACTIVE` (HTTP 409) — moves occupancy to `ENDED`, computes `final_fee_cents`, and returns the plot from `ASSIGNED` to `AVAILABLE` (incrementing the plot's `version`) with no automatic re-offer. Forfeiting, described in §3.8, follows the same fee reconciliation but re-offers the plot. In both closings, if the assignment's `fee_status` is still `UNPAID`, the gardener's `balance_owed_cents` is adjusted by the difference between the final and provisional fees — that is, the final fee minus the provisional fee is added to the ledger — so that the amount owed is reconciled from the provisional estimate to the settled final figure.

The money axis is the exclusive province of the `Treasurer`. Recording a payment requires the assignment's `fee_status` to be `UNPAID` (otherwise `ERR_FEE_NOT_PAYABLE`, HTTP 409) and carries an `amount_cents` that must equal the currently owed fee — the `final_fee_cents` if it has been set, otherwise the `provisional_fee_cents`; a wrong figure is rejected with `ERR_AMOUNT_MISMATCH` (HTTP 422). A payment moves `fee_status` from `UNPAID` to `PAID` and subtracts `amount_cents` from the gardener's `balance_owed_cents`. Waiving a fee likewise requires `fee_status` to be `UNPAID` (`ERR_FEE_NOT_PAYABLE` otherwise), moves it to `WAIVED`, and subtracts the outstanding fee (the `final_fee_cents` if set, else the `provisional_fee_cents`) from `balance_owed_cents`. Refunding requires `fee_status` to be `PAID` (`ERR_FEE_NOT_REFUNDABLE`, HTTP 409 otherwise) and an `amount_cents` equal to the amount previously paid (`ERR_AMOUNT_MISMATCH` otherwise); it moves `fee_status` to `REFUNDED` and adds `amount_cents` back to `balance_owed_cents` as a compensating entry.

### 3.7. Renewing a Lease Across Seasons

Continuity of tenancy runs through a two-step renewal on the occupancy axis. A leaseholder initiates renewal on their own assignment, which advances `occupancy_status` from `ACTIVE` to `RENEWAL_PENDING`. This step is available only while the assignment is `ACTIVE`; a request against any other occupancy state is rejected with `ERR_ASSIGNMENT_NOT_ACTIVE` (HTTP 409). Two further gates guard renewal, and they are checked before the balance gate: the assignment must have no compliance case in `OPEN`, `WARNED`, or `ESCALATED`, otherwise the request is rejected with `ERR_RENEWAL_BLOCKED_BY_COMPLIANCE` (HTTP 409); and the gardener's `balance_owed_cents` must be exactly zero, otherwise the request is rejected with `ERR_OUTSTANDING_BALANCE` (HTTP 402).

A `GardenManager` then confirms the pending renewal. Confirmation requires the assignment's `occupancy_status` to be `RENEWAL_PENDING` (otherwise `ERR_RENEWAL_NOT_PENDING`, HTTP 409), and it re-applies the same two guards: no compliance case in `OPEN`, `WARNED`, or `ESCALATED` (`ERR_RENEWAL_BLOCKED_BY_COMPLIANCE`) and a `balance_owed_cents` of exactly zero (`ERR_OUTSTANDING_BALANCE`). A confirmed renewal advances the current assignment from `RENEWAL_PENDING` to `RENEWED` — a terminal occupancy state for that row — and in the same operation mints a fresh assignment for the next season on the same plot, whose `renewed_from_assignment_id` points back to the assignment just renewed and which begins `ACTIVE` on the occupancy axis and `UNPAID` on the fee axis. Confirming also increments the gardener's `tenure_seasons` by one, which in turn raises that gardener's renewal priority score for any future allocation.

### 3.8. Compliance, Curing, and Forfeiture

Rule and abandonment violations are handled through a graduated compliance process that a `GardenManager` drives. Opening a compliance case names the `assignment_id` under review and a `violation_type` of `NEGLECT`, `RULE_BREACH`, `UNPAID_FEE`, or `WATER_ABUSE`. A new case is `OPEN` — the `status` axis ranges over `OPEN`, `WARNED`, `CURED`, and `ESCALATED` — records its `opened_on` at the current clock, denormalizes the assignment's `gardener_id` onto the case, and records a strike against the gardener. Recording the strike increments the gardener's `strike_count`, and the gardener's `standing` is then recomputed from that count: a `strike_count` of 0 yields `GOOD`, a count of 1 or 2 yields `PROBATION`, and a count of 3 or more yields `SUSPENDED`. Because a strike moves standing and count, it also lowers the gardener's live renewal priority score. Cases can be read individually and listed with filters on `assignment_id`, `gardener_id`, and `status`.

Issuing a warning requires the case to be `OPEN` (otherwise `ERR_COMPLIANCE_NOT_OPEN`, HTTP 409); it moves the case from `OPEN` to `WARNED` and sets its `cure_deadline` to the current clock plus a fixed cure grace period of exactly 14 days (`CURE_GRACE_DAYS` = 14). The `cure_deadline` is null until a case is warned.

From `WARNED`, a case can be either cured or escalated, and the branch is decided strictly by the clock against the `cure_deadline`. Resolving requires the case to be `WARNED` (`ERR_COMPLIANCE_NOT_WARNED`, HTTP 409 otherwise) and the clock to be at or before the `cure_deadline`; resolving after the deadline is rejected with `ERR_CURE_PERIOD_EXPIRED` (HTTP 409). A successful resolve moves the case from `WARNED` to `CURED` — terminal — which lifts the compliance block on the assignment's renewal. Escalating is the mirror image: it also requires the case to be `WARNED` (`ERR_COMPLIANCE_NOT_WARNED`), but requires the clock to be strictly after the `cure_deadline`; escalating at or before the deadline is rejected with `ERR_CURE_PERIOD_ACTIVE` (HTTP 409). An escalation moves the case from `WARNED` to `ESCALATED` — terminal — and forces the linked assignment into forfeiture.

Forfeiture, whether triggered directly by a `GardenManager` or cascaded from an escalation, drives an assignment whose `occupancy_status` is `ACTIVE` or `RENEWAL_PENDING` to `FORFEITED` (a direct forfeit against any other occupancy state fails with `ERR_ASSIGNMENT_NOT_ACTIVE`). Forfeiture computes `final_fee_cents` using the final-fee reconciliation of §3.6 and, when the fee is still `UNPAID`, adjusts the gardener's `balance_owed_cents` by the final-minus-provisional difference exactly as settlement does. It then returns the plot from `ASSIGNED` to `AVAILABLE` and, unlike settlement, immediately attempts to re-offer that freed plot to the top-ranked `WAITLISTED` applicant — a transitive cascade that carries the plot on from `AVAILABLE` to `RESERVED` and the selected application from `WAITLISTED` to `OFFERED`. This auto-offer is conditional: if no eligible waitlisted applicant exists for the plot's garden and size, the plot simply remains `AVAILABLE` and no offer is made. Each plot-status change in this chain increments the plot's `version`.

### 3.9. Shared Tools and the Shed

The shed and its tools are available only to gardeners with skin in the game. Before a gardener may check out a tool or book the shed, they must hold at least one assignment with `occupancy_status` of `ACTIVE` in the relevant garden; a gardener without such an active assignment is rejected with `ERR_NOT_ACTIVE_GARDENER` (HTTP 403).

Checking out a tool names the `tool_id`, the borrower's `gardener_id`, the loan start `checked_out_at`, and the scheduled return `due_at`, which must be strictly after `checked_out_at`. A new loan begins in `CHECKED_OUT` (the `status` axis ranges over `CHECKED_OUT`, `RETURNED`, and `RETURNED_LATE`), with `returned_at` null and `late_fine_cents` at 0. A tool cannot be double-booked: the requested interval from `checked_out_at` to `due_at` must not intersect the occupied window of any non-returned loan of the same tool. That occupied window runs from the existing loan's `checked_out_at` up to its effective end plus the tool's `cleaning_buffer_hours`, where the effective end is the loan's `returned_at` if set and otherwise its `due_at`. An intersecting request is rejected with `ERR_TOOL_TIME_CONFLICT` (HTTP 409).

Returning a tool supplies the `returned_at` instant and requires the loan to still be `CHECKED_OUT` (otherwise `ERR_LOAN_NOT_OUTSTANDING`, HTTP 409). The return time decides both the terminal state and any fine. If `returned_at` is at or before `due_at`, the loan is on time: it moves to `RETURNED` and its `late_fine_cents` is 0 — the boundary is inclusive, so a return exactly at `due_at` incurs no fine. If `returned_at` is strictly after `due_at`, the loan moves to `RETURNED_LATE` and a fine is assessed: the lateness is measured as the elapsed time from `due_at` to `returned_at` rounded up to a whole number of hours (any partial hour counts as a full hour), and `late_fine_cents` is that whole-hour count multiplied by 200 cents per hour.

Booking the shed names the `garden_id`, the booking `gardener_id`, the reservation window from `starts_at` (inclusive) to `ends_at` (exclusive, and required to be strictly after `starts_at`), and a `purpose` of `STORAGE`, `WORKSHOP`, or `MEETING`. A booking window must not intersect any existing shed booking for the same garden, or the request is rejected with `ERR_SHED_TIME_CONFLICT` (HTTP 409); as with plot seasons, the interval is half-open with no buffer, so bookings that merely touch at a boundary are allowed. Shed bookings can be listed both per garden and per gardener.

## 4. Endpoint Definitions

The API is a flat topology in which each collection is a top-level resource path. Endpoints that create a brand-new resource return HTTP 201; endpoints that modify existing state or drive a transition return HTTP 200; reads return HTTP 200. The table below lists the method, path, a short description, and the authorized roles for each endpoint. Request and response bodies are not repeated here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/_clock/set_current_utc` | Set the server logical clock | GardenManager |
| POST | `/gardens` | Create a garden with its season window | GardenManager |
| GET | `/gardens/{id}` | Read a garden | GardenManager, Gardener, Treasurer |
| GET | `/gardens/{id}/tools` | List tools in the garden's shed | GardenManager, Gardener, Treasurer |
| GET | `/gardens/{id}/shed-bookings` | List shed bookings for the garden | GardenManager, Gardener, Treasurer |
| POST | `/gardens/{id}/expire-offers` | Expire lapsed offers in the garden, releasing plots | GardenManager |
| POST | `/plots` | Create a plot in a garden | GardenManager |
| GET | `/plots/{id}` | Read a plot | GardenManager, Gardener, Treasurer |
| GET | `/plots` | List/filter plots | GardenManager, Gardener, Treasurer |
| POST | `/plots/{id}/offer` | Offer an available plot to the top-ranked eligible applicant | GardenManager |
| POST | `/plots/{id}/assign` | Directly assign an available plot (OCC-guarded) | GardenManager |
| POST | `/gardeners` | Register a gardener | GardenManager |
| GET | `/gardeners/{id}` | Read a gardener | GardenManager, Gardener, Treasurer |
| GET | `/gardeners/{id}/shed-bookings` | List a gardener's shed bookings | GardenManager, Gardener, Treasurer |
| POST | `/applications` | Submit a waitlist application | Gardener |
| GET | `/applications/{id}` | Read an application | GardenManager, Gardener, Treasurer |
| GET | `/applications` | List/filter applications | GardenManager, Gardener, Treasurer |
| POST | `/applications/{id}/accept` | Accept an offer; creates the assignment | Gardener |
| POST | `/applications/{id}/decline` | Decline an offer; releases the plot | Gardener |
| GET | `/assignments/{id}` | Read an assignment | GardenManager, Gardener, Treasurer |
| GET | `/assignments` | List/filter assignments | GardenManager, Gardener, Treasurer |
| POST | `/assignments/{id}/request-renewal` | Leaseholder requests renewal for next season | Gardener |
| POST | `/assignments/{id}/confirm-renewal` | Manager confirms renewal; mints next-season assignment | GardenManager |
| POST | `/assignments/{id}/settle` | Close an assignment at season end (no auto-offer) | GardenManager |
| POST | `/assignments/{id}/forfeit` | Forfeit an assignment; frees and re-offers the plot | GardenManager |
| POST | `/assignments/{id}/pay` | Record payment of the assignment fee | Treasurer |
| POST | `/assignments/{id}/waive-fee` | Waive the assignment fee | Treasurer |
| POST | `/assignments/{id}/refund` | Refund a previously paid fee | Treasurer |
| POST | `/work-logs` | Log work hours against an assignment | Gardener |
| GET | `/assignments/{id}/work-logs` | List work logs for an assignment | GardenManager, Gardener, Treasurer |
| POST | `/water-readings` | Record a per-period water meter reading | Gardener |
| GET | `/assignments/{id}/water-readings` | List water readings for an assignment | GardenManager, Gardener, Treasurer |
| POST | `/compliance-cases` | Open a compliance case; records a strike | GardenManager |
| GET | `/compliance-cases/{id}` | Read a compliance case | GardenManager, Gardener, Treasurer |
| GET | `/compliance-cases` | List/filter compliance cases | GardenManager, Gardener, Treasurer |
| POST | `/compliance-cases/{id}/warn` | Issue a warning and start the cure clock | GardenManager |
| POST | `/compliance-cases/{id}/resolve` | Mark the violation cured within the grace window | GardenManager |
| POST | `/compliance-cases/{id}/escalate` | Escalate an uncured violation; forfeits the assignment | GardenManager |
| POST | `/tools` | Add a shared tool to a garden's shed | GardenManager |
| POST | `/tool-loans` | Check out a shared tool over a time window | Gardener |
| GET | `/tool-loans/{id}` | Read a tool loan | GardenManager, Gardener, Treasurer |
| GET | `/tool-loans` | List/filter tool loans | GardenManager, Gardener, Treasurer |
| POST | `/tool-loans/{id}/return` | Return a checked-out tool; assesses any late fine | Gardener |
| POST | `/shed-bookings` | Book the shared shed over a time window | Gardener |

## 5. Error Code Catalogue

The trigger conditions for each error are described inline with the workflows in §2 and §3. The table records only the error identifier and its HTTP status code.

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_GARDEN_NOT_FOUND` | 404 |
| `ERR_PLOT_NOT_FOUND` | 404 |
| `ERR_GARDENER_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 |
| `ERR_COMPLIANCE_CASE_NOT_FOUND` | 404 |
| `ERR_TOOL_NOT_FOUND` | 404 |
| `ERR_TOOL_LOAN_NOT_FOUND` | 404 |
| `ERR_PLOT_NOT_AVAILABLE` | 409 |
| `ERR_OFFER_NOT_PENDING` | 409 |
| `ERR_ASSIGNMENT_NOT_ACTIVE` | 409 |
| `ERR_RENEWAL_NOT_PENDING` | 409 |
| `ERR_FEE_NOT_PAYABLE` | 409 |
| `ERR_FEE_NOT_REFUNDABLE` | 409 |
| `ERR_COMPLIANCE_NOT_OPEN` | 409 |
| `ERR_COMPLIANCE_NOT_WARNED` | 409 |
| `ERR_LOAN_NOT_OUTSTANDING` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_RENEWAL_BLOCKED_BY_COMPLIANCE` | 409 |
| `ERR_NOT_ACTIVE_GARDENER` | 403 |
| `ERR_SIZE_MISMATCH` | 409 |
| `ERR_NO_ELIGIBLE_APPLICANT` | 409 |
| `ERR_DUPLICATE_APPLICATION` | 409 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_AMOUNT_MISMATCH` | 422 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_CURE_PERIOD_EXPIRED` | 409 |
| `ERR_CURE_PERIOD_ACTIVE` | 409 |
| `ERR_PLOT_SEASON_CONFLICT` | 409 |
| `ERR_TOOL_TIME_CONFLICT` | 409 |
| `ERR_SHED_TIME_CONFLICT` | 409 |
| `ERR_OUTSTANDING_BALANCE` | 402 |
