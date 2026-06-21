# Community Solar API — Product Requirements Document

## 1. Introduction

Community solar lets utility customers who cannot put panels on their own roof — renters, shaded homes, low-income households — buy a share of a shared solar garden and receive monthly bill credits proportional to what their slice of the array produces. This document specifies the backend service that runs such a program end to end: it tracks each solar garden's subscribable capacity, enrolls and activates subscribers onto capacity shares, opens monthly billing periods, distributes each period's production across active shares, converts those distributions into provisional and then metered bill credits, reconciles the metered credits into on-bill savings, and tracks the Renewable Energy Certificates (RECs) the garden mints.

The program sits at the intersection of two hard problems. The first is **quota allocation**: a garden has a fixed nameplate capacity, a slice of which is legally reserved for low-income subscribers, and the service must keep its committed-versus-available accounting exact as enrollments activate, subscriptions cancel, shares transfer between subscribers, and a waitlist drains into freed capacity. The second is **ledger reconciliation**: every month's production must be distributed to the penny-equivalent (whole kWh and integer cents), first against a forecast and later against the actual meter reading, with the metered figures flowing through credit issuance, on-bill application, dispute handling, overproduction true-up, and REC minting — all while keeping the garden's derived totals consistent.

Three operator perspectives share the system. A grid operator owns the gardens, the monthly metering epoch, reconciliation, and REC minting; a program administrator handles enrollment review, the low-income carve-out, waitlist promotion, dispute resolution, and REC disposition; and subscribers act on their own enrollments, transfers, cancellations, waitlist entries, and disputes. Because metering and capacity accounting are subject to genuine concurrent writes, the service uses optimistic concurrency control on the two entities most exposed to races — the solar project and the billing period.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. The `X-User-Role` header must be present and must name one of exactly three roles, spelled precisely: `GridOperator`, `ProgramAdmin`, and `Subscriber`. A request missing the role header, or carrying a value that is not one of these three, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but is not permitted to perform the requested operation under the access matrix is rejected with `ERR_FORBIDDEN` (HTTP 403).

The three roles differ in how `X-User-ID` ties to the data. When `X-User-Role` is `GridOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. Likewise, when `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, recorded but never compared to an entity `id`. When `X-User-Role` is `Subscriber`, `X-User-ID` is the `id` of the acting `Subscriber`; ownership checks on any resource that references a `Subscriber` compare that resource's subscriber foreign key to `X-User-ID`, and a failed ownership check is reported as `ERR_FORBIDDEN` (HTTP 403). This resource-ownership check runs only after path existence and referential existence have passed — so a request naming a path resource or body foreign key that does not exist surfaces `ERR_NOT_FOUND` or `ERR_REFERENCE_NOT_FOUND` first — but before required-field, range, state-validity, and business-rule checks, so an ownership mismatch surfaces ahead of those.

The grid operator is the only role that may create a project, open a billing period, set a meter reading, reconcile a period, sweep its true-up, reopen it, close it, issue an on-bill credit, and apply that credit to lifetime savings. The program administrator is the only role that may register a subscriber, change a project's carve-out percentage, approve, reject, or activate an enrollment, suspend or resume a subscription, resolve a dispute, and earmark, retire, or transfer a REC batch. The subscriber is the only role that may submit or resubmit an enrollment, transfer their own subscription, cancel their own subscription, withdraw their own waitlist entry, and dispute their own reconciliation. Creating an enrollment and queuing a waitlist entry are shared between `Subscriber` and `ProgramAdmin`. Read access to projects, subscribers, periods, subscriptions, enrollments, allocations, reconciliations, waitlist entries, and REC batches is shared across all three roles, except that REC batch reads are limited to `GridOperator` and `ProgramAdmin`.

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter defaults to 0 and has no upper bound beyond what the dataset supports; its minimum is 0. A non-integer `limit` or `offset`, or a `limit` below 1 or above 100, or an `offset` below 0, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400). List results are sorted by `created_at` in ascending order, with records that share the same `created_at` ordered by their creation sequence (insertion order). Each list response surfaces, inside its `meta` object, the `limit` and `offset` in effect together with `total_count` (the total number of matching records before pagination) and `has_more` (a boolean that is true when records remain beyond the current page).

### 2.4. Common Resource Properties and Versioning

Every resource carries a server-minted `id` that is a UUID with no type prefix. All timestamps — `created_at` and `updated_at` — are ISO 8601 UTC strings with three fractional digits. Most entities also carry a `version`, an integer that begins at its initial value when the resource is created and increments by one each time the resource is mutated, alongside a refresh of `updated_at`. These common fields are present on the solar project, subscriber, enrollment, subscription, waitlist entry, billing period, allocation, reconciliation, and REC batch.

One resource is the exception. The carve-out adjustment is an append-only audit record: it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it is never mutated after creation. Any attempt to run a state transition or update against this append-only resource is rejected with `ERR_IMMUTABLE_RESOURCE` (HTTP 409).

### 2.5. Ledger Consistency and Cascading Recomputation

The service maintains a set of **derived ledger fields** that must always agree with the underlying rows. On the solar project these include `committed_kw`, `carve_out_committed_kw`, `available_kw`, `carve_out_available_kw`, `rec_minted_total`, `rec_retired_total`, `rec_available_balance`, `total_net_savings_cents`, and `status`. On the billing period these include `distributable_kwh`, `allocated_kwh_total`, `overproduction_kwh`, `rollover_kwh`, `forfeited_kwh`, `rollover_credit_cents`, and `rec_minted_count`. On the subscriber these include `churn_risk_score` and `lifetime_savings_cents`. None of these is supplied by the client; each is recomputed by the service whenever a triggering event occurs, and every such recomputation is part of the same atomic request that caused it — there is no deferred or eventual settlement. When a transition mutates a parent entity as a side effect (for example, an activation that advances the project's committed capacity), that parent's `version` increments and its `updated_at` refreshes in the same operation.

`committed_kw` is the sum of `share_kw` across all subscriptions of the project whose status is `ACTIVE`, `SUSPENDED`, or `TRANSFERRING`. `carve_out_committed_kw` is the same sum restricted to subscriptions whose `is_carve_out` is true. `available_kw` is the project's `nameplate_capacity_kw` minus `committed_kw`, never allowed to fall below zero. The project's `status` is `OPEN` while `available_kw` is greater than zero and becomes `FULL` exactly when `available_kw` reaches zero.

### 2.6. Capacity, Carve-Out, and Project Status Invariants

A solar project is created with a `name`, a two-letter `state_code` identifying its utility jurisdiction, a `nameplate_capacity_kw` that must be greater than zero, an integer `credit_rate_cents_per_kwh` of at least zero, an optional `carve_out_pct`, and an optional `program_fee_rate`. The carve-out percentage defaults to 0.40 and must lie between 0 and 1 inclusive; the program fee rate defaults to 0.10 and must be at least 0 and strictly less than 1. The carve-out reserves a slice of the array for low-income subscribers: `carve_out_available_kw` is `nameplate_capacity_kw` multiplied by `carve_out_pct`, rounded to three decimal places, minus `carve_out_committed_kw`, and floored at zero so it never goes negative. Field values outside their allowed ranges — a carve-out percentage outside the 0-to-1 interval, or a negative share or usage figure — are rejected with `ERR_VALIDATION` (HTTP 422).

### 2.7. Precision and Rounding

Capacity is carried in kW as a number. Credits, fees, savings, and rollover values are integer cents throughout — there are no fractional cents. Allocated production is carried as whole kWh. RECs are whole counts. Where a calculation produces a non-integer intermediate that must land on an integer result, the rounding method is **round half up** unless a step explicitly calls for a floor or a ceiling. The carve-out reservation term uses three-decimal rounding on the `nameplate_capacity_kw * carve_out_pct` product before the carve-out commitment is subtracted; the tiered program fee uses a single round-half-up at the end; the rollover cap uses a ceiling on its capacity term; and per-share allocation uses a floor before remainder distribution.

### 2.8. Optimistic Concurrency Control

Two write operations carry an optimistic-concurrency guard tied to the current `version` of a parent entity, so that a client cannot blindly overwrite state it has not observed.

Transferring a subscription to a new subscriber must carry an `expected_project_version` field whose value equals the target project's current `version`. If another writer has advanced the project's `version` since the client last read it — because, for instance, another enrollment activated or another transfer completed — the transfer is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). This guard exists because a transfer revalidates carve-out membership against the project ledger, and a stale `expected_project_version` would mean that revalidation runs against an outdated `carve_out_available_kw` baseline.

Setting a meter reading on a billing period must carry an `expected_period_version` field whose value equals that period's current `version`. If the period's `version` has advanced since the client last read it — because a prior meter write already re-ran the allocation waterfall over a pool the client never saw — the meter write is rejected with `ERR_STALE_PERIOD_VERSION` (HTTP 412). The reconcile operation likewise checks `expected_period_version` against the billing period's current `version` and rejects a mismatch with `ERR_STALE_PERIOD_VERSION` (HTTP 412). No other endpoint takes a version field.

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the failure surfaced is deterministic. The order is: first, authentication — the role header must be present and known, else `ERR_UNAUTHENTICATED`. Second, authorization — the role must be permitted for the operation, else `ERR_FORBIDDEN`. Third, path existence — every resource id named in the URL path must exist, validated left to right, else `ERR_NOT_FOUND`. Fourth, referential existence — every foreign key in the request body (such as `project_id`, `subscriber_id`, or `target_subscriber_id`) must reference an existing resource, else `ERR_REFERENCE_NOT_FOUND`. Fifth, required-field presence and typing — required body fields must be present and well-typed (for example `requested_share_kw`, `metered_production_kwh`, or `period_month`), else `ERR_INVALID_REQUEST`. Sixth, range validation, else `ERR_VALIDATION`. Seventh, uniqueness, else `ERR_DUPLICATE_RESOURCE`. Eighth, state validity — the target resource must be in a state from which the requested transition is defined, else `ERR_INVALID_STATE`. Ninth, the optimistic-concurrency version check, else the relevant stale-version error. Only after all of these pass are the operation-specific business rules — carve-out, jurisdiction, usage cap, capacity, project-full, dispute, and the various REC and meter guards described throughout §3 — evaluated.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Garden and Adjusting the Carve-Out

A `GridOperator` brings a garden online by creating a solar project. At creation the project starts `OPEN`, its `committed_kw` and all REC balances are zero, and its `available_kw` equals the full `nameplate_capacity_kw`. From that moment the project exposes its full derived ledger on read: committed and available capacity, the carve-out figures, the three REC running totals (`rec_minted_total`, `rec_retired_total`, `rec_available_balance`), and `total_net_savings_cents`, which is the sum of `net_savings_cents` across all of the project's reconciliations whose credit dimension has reached `APPLIED`.

Over a garden's life the low-income reservation may need to move. A `ProgramAdmin` records a carve-out adjustment by supplying a `new_carve_out_pct` and a `reason`. The service captures the prior fraction into `previous_carve_out_pct`, writes `new_carve_out_pct` onto the project's `carve_out_pct`, recomputes `carve_out_available_kw` from the new fraction, and increments the project's `version` by one. The new fraction must lie between 0 and 1 inclusive; a value outside that range is an `ERR_VALIDATION` (HTTP 422). The adjustment record is append-only and immutable once written. The list of a project's adjustments is reachable in reverse from the project through each adjustment's `project_id`.

### 3.2. Registering Subscribers and the Churn-Risk Snapshot

A `ProgramAdmin` registers a utility subscriber with a `full_name`, a `utility_account_no`, a `state_code` naming the jurisdiction of that utility account, an optional `is_low_income` flag (defaulting to false), and a self-reported `annual_usage_kwh` that must be an integer of at least zero. The `utility_account_no` must be unique across all subscribers; a collision is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409). On registration the subscriber's `lifetime_savings_cents` starts at zero and its `churn_risk_score` is initialized.

The `churn_risk_score` is a weighted integer from 0 to 100 capturing how likely a subscriber is to leave the program. It is recomputed whenever a subscription of theirs is suspended, resumed, or cancelled, and whenever one of their reconciliations is disputed or its dispute resolved. In its default **snapshot** form the score reflects only current flags: it starts at zero, adds 40 if the subscriber has any subscription currently in `SUSPENDED`, adds 35 if the subscriber has any reconciliation whose dispute dimension is currently `DISPUTED`, and adds 10 if the subscriber's `is_low_income` is true; the running total is then capped so it never exceeds 100. The snapshot form ignores history and does not apply the recent-cancellation weight. A **trailing** variant applies when the subscriber has had a subscription cancelled within the last three `CLOSED` periods: it adds a further 50 to the base before the cap at 100 is applied. Concretely, the trailing weight applies when the subscriber has any `CANCELLED` subscription whose `cancellation_effective_period_id` names a period that is itself `CLOSED` and ranks among the three highest-`sequence_index` `CLOSED` periods of that period's project; a cancelled subscription with no `cancellation_effective_period_id`, or whose effective period is not yet `CLOSED`, does not contribute the trailing weight. The subscriber's `lifetime_savings_cents` is the sum of `net_savings_cents` across that subscriber's reconciliations whose credit dimension is `APPLIED`.

### 3.3. The Enrollment Review Loop

Joining a garden begins with an enrollment, a request from a `Subscriber` (or a `ProgramAdmin` acting for one) naming a `project_id`, a `subscriber_id`, and a `requested_share_kw` greater than zero. A new enrollment starts in `DRAFT`. The enrollment also carries a `rejection_reason`, populated only when it is turned away, and a `subscription_id`, populated only once it activates into a live subscription. Enrollments can be listed and filtered in reverse from a project, a subscriber, or a subscription via the `project_id`, `subscriber_id`, and `subscription_id` keys.

A `Subscriber` moves a `DRAFT` enrollment to `SUBMITTED` by submitting it. Submission is gated by three business checks. The project must not be `FULL`: a submit against a `FULL` project is rejected with `ERR_PROJECT_FULL` (HTTP 409). The `requested_share_kw` must be no greater than the project's `available_kw`, else `ERR_CAPACITY_EXCEEDED` (HTTP 409). And the requested share must fit the subscriber's self-reported consumption under the **annual-usage cap**: the `requested_share_kw` multiplied by 1000 must be no greater than the subscriber's `annual_usage_kwh`, else `ERR_USAGE_CAP_EXCEEDED` (HTTP 409). Submitting commits no capacity; capacity is reserved only at activation.

A `ProgramAdmin` reviews a `SUBMITTED` enrollment. Approval moves it from `SUBMITTED` to `APPROVED`. If the subscriber is low-income, approval additionally requires that the `requested_share_kw` fit within the project's `carve_out_available_kw`; otherwise approval is rejected with `ERR_CARVE_OUT_EXCEEDED` (HTTP 409). Approval still commits no capacity. Alternatively the admin may reject the enrollment: a `SUBMITTED → REJECTED` or an `APPROVED → REJECTED` rejection records the supplied `rejection_reason` on the enrollment. A `REJECTED` enrollment is not dead — its subscriber may resubmit it, moving `REJECTED → SUBMITTED` again, which clears the prior `rejection_reason` and re-enters review. That resubmission re-checks the same project-not-`FULL` gate (`ERR_PROJECT_FULL`) and the same capacity gate (`requested_share_kw` no greater than `available_kw`, else `ERR_CAPACITY_EXCEEDED`). This reject-then-resubmit cycle is the enrollment machine's revision loop.

### 3.4. Activation: Committing Capacity and Sealing the Ledger

Activation is where a garden's capacity is actually spent. A `ProgramAdmin` activates an `APPROVED` enrollment, moving it from `APPROVED` to `ACTIVATED` and minting a live subscription in one atomic step. Two final gates run at activation time, recomputed against the live ledger because capacity may have moved since approval: the `requested_share_kw` must still be no greater than the project's `available_kw` (else `ERR_CAPACITY_EXCEEDED`), and if the subscriber is low-income the `requested_share_kw` must still fit within `carve_out_available_kw` (else `ERR_CARVE_OUT_EXCEEDED`).

When activation succeeds, the service creates a `Subscription` in status `ACTIVE` whose `share_kw` is copied from the enrollment's `requested_share_kw` and whose `is_carve_out` is set to whatever the subscriber's `is_low_income` was at activation, pinning carve-out accounting for the life of that subscription. The new subscription records its `project_id`, `subscriber_id`, and `enrollment_id`. The enrollment's `subscription_id` is set to point back at it. The project ledger is then resynced: `committed_kw` increases by the committed `share_kw`, and `available_kw`, `carve_out_committed_kw`, and `carve_out_available_kw` are all recomputed. If `available_kw` reaches zero, the project's `status` flips to `FULL`. The project's `version` increments by one.

### 3.5. The Living Subscription: Suspend, Resume, Transfer, Cancel

A subscription is the durable membership that earns monthly allocations. It begins `ACTIVE` and carries its `project_id`, `subscriber_id`, `enrollment_id`, `share_kw`, `is_carve_out`, an optional `transferred_from_subscription_id` self-reference set when the row was born from a transfer, and an optional `cancellation_effective_period_id` recording the period at or after which it stops earning. Subscriptions are listable and filterable in reverse by `project_id`, `subscriber_id`, `enrollment_id`, `transferred_from_subscription_id`, and `cancellation_effective_period_id`.

A `ProgramAdmin` may suspend an `ACTIVE` subscription, moving it `ACTIVE → SUSPENDED`. A suspended subscription stops earning new provisional allocations from the next `OPEN` period onward, but its `share_kw` remains counted in the project's `committed_kw` — the capacity stays reserved — and the subscriber's `churn_risk_score` is recomputed (suspension raises risk). Resuming moves `SUSPENDED → ACTIVE`; the subscription resumes earning allocations from the next `OPEN` period and the `churn_risk_score` is recomputed again (resumption lowers risk). This suspend-and-resume pairing is a cycle the subscription may traverse repeatedly.

A `Subscriber` may transfer their own `ACTIVE` subscription to another subscriber, naming a `target_subscriber_id` and the optimistic-concurrency `expected_project_version`. The target subscriber must exist, and the target's `state_code` must match the project's `state_code`; a jurisdiction mismatch is rejected with `ERR_TRANSFER_JURISDICTION_MISMATCH` (HTTP 409). The `expected_project_version` must match the project's current `version`, else `ERR_STALE_PROJECT_VERSION` (HTTP 412). On success the service creates a successor subscription in status `ACTIVE` owned by the target, copying the same `share_kw`, setting `transferred_from_subscription_id` to the original subscription's id, and setting the successor's `is_carve_out` from the target subscriber's `is_low_income`. Because carve-out membership may flip when the new owner's low-income status differs from the original's, `carve_out_committed_kw` is recomputed. The original subscription moves to `TRANSFERRING` and is then immediately driven to `CANCELLED` by a system edge once the successor is `ACTIVE`. Across the whole transfer the net change to `committed_kw` is zero, because the successor holds the same `share_kw`; when the original is cancelled by that system edge, its `cancellation_effective_period_id` is set to the project's current `OPEN` period if one exists, and when more than one `OPEN` period exists for the project the one with the greatest `sequence_index` is used. The project's `version` increments by one. The transfer loop — original `ACTIVE → TRANSFERRING`, successor born `ACTIVE`, original `TRANSFERRING → CANCELLED` — conserves the share.

Cancellation ends a membership and frees its capacity. A `Subscriber` may cancel either an `ACTIVE` or a `SUSPENDED` subscription, moving it to `CANCELLED`. On cancellation the project ledger releases the share: `committed_kw` decreases by the subscription's `share_kw`, and `available_kw`, `carve_out_committed_kw`, and `carve_out_available_kw` are recomputed. If the project was `FULL` and now has room (its `available_kw` is greater than zero), its `status` returns to `OPEN`. The subscription's `cancellation_effective_period_id` is set to the project's current `OPEN` period if one exists, so it earns no allocations from that period forward. The subscriber's `churn_risk_score` is recomputed (cancellation sets the churn floor). The project's `version` increments by one. Cancelling also triggers waitlist auto-promotion, described next. Cancelling a `SUSPENDED` subscription performs the identical ledger resync, the same auto-promotion, and the same `version` increment.

### 3.6. The Waitlist and Auto-Promotion

When a garden is `FULL`, a would-be member does not enroll directly; instead a `Subscriber` (or `ProgramAdmin`) queues a waitlist entry naming the `project_id`, the `subscriber_id`, and the `requested_share_kw` they want; the `requested_share_kw` must be greater than zero, else `ERR_VALIDATION` (HTTP 422). Queuing imposes no project-`FULL`, capacity, or carve-out gate — an entry may be queued regardless of the project's current status or available capacity. The entry starts `QUEUED`, and the server stamps a `queued_at` timestamp that serves as the first-in-first-out ordering key. Waitlist entries are listable and filterable in reverse by `project_id`, `subscriber_id`, and `promoted_enrollment_id`. The owner may withdraw a `QUEUED` entry, moving it `QUEUED → WITHDRAWN`; a withdraw attempted on an entry that is not `QUEUED` is rejected with `ERR_WAITLIST_NOT_QUEUED` (HTTP 409).

Promotion happens automatically when capacity frees up at cancellation. Among the project's `QUEUED` waitlist entries, the service picks the oldest by `queued_at` ascending, breaking ties by `created_at` ascending, whose `requested_share_kw` is no greater than the project's now-available `available_kw`. That entry is moved to `PROMOTED`, and the promotion mints a fresh enrollment for it; the entry's `promoted_enrollment_id` records that minted enrollment's id. This promotion is a cascade off the cancellation that freed the capacity. An entry that remains `QUEUED` or that has been `WITHDRAWN` was never promoted, so its `promoted_enrollment_id` stays empty.

### 3.7. Opening a Billing Period and the Allocation Waterfall

A `GridOperator` opens a monthly billing period for a project by supplying the `project_id`, a `period_month` formatted `YYYY-MM`, and a `forecast_production_kwh` that must be an integer of at least zero. The `period_month` must be unique within the project; a duplicate is rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409). On creation the period starts `OPEN`, the service assigns it a `sequence_index` — a monotonic per-project ordering index (0, 1, 2, …) used to compare period order — and immediately runs the allocation waterfall on the forecast basis, distributing the forecast across eligible subscriptions and creating one `PROVISIONAL` allocation per eligible subscription. Periods can be listed and filtered in reverse by `project_id`.

The **allocation waterfall** distributes a pool of whole kWh across eligible subscriptions in proportion to their share, with a pinned rounding-then-remainder procedure so the distributed total exactly equals the pool. The pool is the period's `distributable_kwh`. A subscription is **eligible** for a period if its status is `ACTIVE` and either it has no `cancellation_effective_period_id` or the period named by its `cancellation_effective_period_id` has a `sequence_index` strictly greater than this period's `sequence_index`. Subscriptions in `SUSPENDED` are excluded and earn nothing while suspended. If the sum of `share_kw` across eligible subscriptions is zero, every allocation's `allocated_kwh` is zero and the entire pool becomes the period's overproduction. Otherwise the procedure runs in this exact order: first compute, for each eligible subscription, a raw amount equal to the pool multiplied by that subscription's `share_kw` divided by the total eligible share; second, take the floor of each raw amount to get whole kWh per share; third, compute the leftover as the pool minus the sum of those floors; fourth, hand out the leftover one kWh at a time to eligible subscriptions ordered by descending fractional part of their raw amount, breaking ties by ascending subscription `created_at`. Each subscription's `allocated_kwh` is its floor plus one if it received a remainder kWh. Each allocation records the `share_kw_snapshot` it was computed against, captured from the subscription at distribution time.

A period's `distributable_kwh` is its `forecast_production_kwh` while the period is `OPEN`, and switches to its `metered_production_kwh` once the period reaches `METERED` or later. The period's `allocated_kwh_total` is the sum of `allocated_kwh` across its allocations in status `PROVISIONAL` or `FINAL`. The period's `overproduction_kwh` is its `distributable_kwh` minus its `allocated_kwh_total` — the unallocated residual carried into true-up.

### 3.8. Provisional and Final Bill Credits

Each allocation carries two credit figures expressing the same idea against two different production bases. At period `OPEN`, on the forecast basis, the allocation's `provisional_credit_cents` is its forecast-basis `allocated_kwh` multiplied by the project's `credit_rate_cents_per_kwh`. Both operands are integers, so the result is integer cents. The allocation's `status` starts `PROVISIONAL`. The `final_credit_cents` is populated only later, at reconciliation, as the metered-basis `allocated_kwh` multiplied by the same `credit_rate_cents_per_kwh`; until then it is empty. The provisional figure is computed once, from the forecast basis at period `OPEN`, and is not recomputed when the period is metered — metering updates each allocation's `allocated_kwh` but leaves `provisional_credit_cents` at its forecast-basis value; the final figure is frozen at reconciliation and is what feeds the reconciliation's gross credit. Allocations are listable and filterable in reverse by `period_id` and `subscription_id`.

### 3.9. Metering: Switching to Actuals

Once the real meter reading is known, a `GridOperator` meters the period, moving it `OPEN → METERED`. The request must supply `metered_production_kwh` (present, an integer, and at least zero — a missing value, a non-integer value, or a value below zero all raise `ERR_METER_READING_REQUIRED`, HTTP 400) and the optimistic-concurrency `expected_period_version` matching the period's current `version` (else `ERR_STALE_PERIOD_VERSION`, HTTP 412). On metering, the period's `distributable_kwh` switches from the forecast to the `metered_production_kwh`, and the allocation waterfall re-runs over the eligible subscriptions on this metered basis — each allocation's `allocated_kwh` is updated while its `status` remains `PROVISIONAL`. The period's `version` increments by one.

### 3.10. Reconciliation: Finalizing Credits, Savings, and RECs

Reconciling a `METERED` period is the heaviest cascade in the system. A `GridOperator` reconciles, moving the period `METERED → RECONCILED`; the request carries `expected_period_version`, which must match the period's current `version`, else `ERR_STALE_PERIOD_VERSION` (HTTP 412). The reconcile fans out in three depths. First, every allocation of the period moves `PROVISIONAL → FINAL` and its `final_credit_cents` is computed on the metered basis. Second, one reconciliation is created per `FINAL` allocation, starting with a credit dimension of `DRAFT` and a dispute dimension of `NONE`, recording its `subscription_id`, `period_id`, and `allocation_id`, and carrying its gross, fee, and net figures. Third, a REC batch is minted from the period and the project's REC running totals are recomputed.

Each reconciliation's `gross_credit_cents` is the `final_credit_cents` of its linked allocation at reconciliation time. The **tiered program fee** is charged on that gross. The base rate is the carve-out fee rate of 0.05 when the subscription's `is_carve_out` is true, and otherwise the project's `program_fee_rate`. A tier multiplier is then selected from the gross: when the gross is at most 5000 cents the multiplier is 1.00; when the gross is above 5000 cents and at most 20000 cents the multiplier is 0.90 (a volume discount); and when the gross is above 20000 cents the multiplier is 0.80. The `program_fee_cents` is the gross multiplied by the base rate multiplied by the tier multiplier, with a single round-half-up applied at the end to whole cents. The `net_savings_cents` is the `gross_credit_cents` minus the `program_fee_cents` — the on-bill savings.

REC minting at reconciliation creates a `RECBatch` recording the `project_id` and `period_id`, in status `MINTED`, whose `rec_count` is the floor of the period's `metered_production_kwh` divided by 1000 (one REC per 1000 metered kWh). The period's own `rec_minted_count` records the same floor. The project's `rec_minted_total` is recomputed as the sum of `rec_count` across REC batches whose period is in `RECONCILED`, `TRUED_UP`, or `CLOSED`. The project's `rec_available_balance` is its `rec_minted_total` minus its `rec_retired_total` minus the sum of `rec_count` over REC batches in status `TRANSFERRED`.

### 3.11. Issuing, Applying, and Disputing Credits

A reconciliation evolves along two independent dimensions held in two fields: `credit_status` and `dispute_status`. The **credit dimension** (`credit_status`) moves `DRAFT → ISSUED → APPLIED`; the **dispute dimension** (`dispute_status`) moves `NONE → DISPUTED → RESOLVED` in parallel and changes while `credit_status` is still `DRAFT` or `ISSUED`. A `GridOperator` issues a `DRAFT` reconciliation, moving the credit dimension `DRAFT → ISSUED`; issuance requires that the linked billing period is in `RECONCILED`, posts the on-bill credit to the utility account, and freezes `net_savings_cents`. The same operator then applies an `ISSUED` reconciliation, moving the credit dimension `ISSUED → APPLIED`; application requires that the dispute dimension is not currently `DISPUTED`, else `ERR_DISPUTE_BLOCKS_APPLY` (HTTP 409). On application the subscriber's `lifetime_savings_cents` increases by the reconciliation's `net_savings_cents` and the project's `total_net_savings_cents` increases by the same amount.

A `Subscriber` may dispute their own reconciliation, moving the dispute dimension `NONE → DISPUTED`, provided the credit dimension has not already reached `APPLIED`; a dispute attempted after the credit was applied is rejected with `ERR_RECON_ALREADY_APPLIED` (HTTP 409). Raising a dispute recomputes the subscriber's `churn_risk_score` (a dispute raises risk). A `ProgramAdmin` resolves a `DISPUTED` reconciliation, moving the dispute dimension `DISPUTED → RESOLVED`, which recomputes the `churn_risk_score` (resolution lowers risk) and unblocks the credit dimension for application. Reconciliations are listable and filterable in reverse by `subscription_id`, `period_id`, and `allocation_id`.

### 3.12. True-Up, Reopen, and Closing the Epoch

After reconciliation a `GridOperator` runs the **true-up**, moving the period `RECONCILED → TRUED_UP`, which sweeps the period's overproduction into a rollover and a forfeiture pinned on the period. The sweep evaluates in a fixed order because its terms depend on one another. First the cap is computed as the smaller of a fixed ceiling of 2000 kWh and the ceiling of the project's `committed_kw` multiplied by 50 kWh per kW. Second, the `rollover_kwh` is the smaller of the period's `overproduction_kwh` and that cap. Third, the `forfeited_kwh` is the `overproduction_kwh` minus the `rollover_kwh`. Fourth, the `rollover_credit_cents` is the `rollover_kwh` multiplied by the project's `credit_rate_cents_per_kwh`. These three computed fields — `rollover_kwh`, `forfeited_kwh`, and `rollover_credit_cents` — are zero until the period is `TRUED_UP`.

A `RECONCILED` period that should not have been finalized can be reopened by a `GridOperator`, moving it `RECONCILED → METERED`, provided no reconciliation of that period has yet reached credit `APPLIED`; a reopen attempted after any reconciliation was applied is rejected with `ERR_RECON_ALREADY_APPLIED` (HTTP 409). Reopening deletes all of the period's reconciliations, moves each allocation `FINAL → PROVISIONAL`, clears each `final_credit_cents`, and resets the minted REC batch so the period's `rec_minted_count` is recomputed at the next reconcile. This reopen edge is what makes the period machine cyclic.

Finally a `GridOperator` closes a `TRUED_UP` period, moving it `TRUED_UP → CLOSED`, but only if every reconciliation of that period has a dispute dimension of either `NONE` or `RESOLVED`; an attempt to close while any reconciliation is still `DISPUTED` is rejected with `ERR_OPEN_DISPUTE_BLOCKS_CLOSE` (HTTP 409). Closing locks the period: any cancelled subscriptions whose `cancellation_effective_period_id` equals this period stop appearing in future waterfalls, and each affected subscriber's `lifetime_savings_cents` is recomputed from their `APPLIED` reconciliations.

### 3.13. REC Disposition

A minted REC batch begins `MINTED` and is dispositioned by a `ProgramAdmin`. First the admin earmarks it, moving `MINTED → ALLOCATED`; this is a bookkeeping step with no ledger change. From `ALLOCATED` the batch forks one of two divergent ways. Retiring it requires a `retirement_beneficiary` (else `ERR_REC_BENEFICIARY_REQUIRED`, HTTP 400) and moves it `ALLOCATED → RETIRED`, which increases the project's `rec_retired_total` by the batch's `rec_count` so the project's `rec_available_balance` falls. Transferring it requires a `transfer_counterparty` (else `ERR_REC_COUNTERPARTY_REQUIRED`, HTTP 400) and moves it `ALLOCATED → TRANSFERRED`, which decreases the project's `rec_available_balance` by the batch's `rec_count` while leaving `rec_retired_total` unchanged — a side effect deliberately divergent from retirement. REC batches are listable and filterable in reverse by `project_id` and `period_id`.

## 4. Endpoint Definitions

All endpoints return the standard envelope of §2.2. Creating a new resource returns HTTP 201 with the created resource in `data`; state transitions and other modifications that do not create a new resource return HTTP 200 with the updated resource. The two exceptions where a transition still mints a brand-new resource — activating an enrollment into a subscription, and transferring a subscription into a successor — return HTTP 201. List and single-resource reads return HTTP 200. Request bodies, response bodies, and side effects are not repeated here; reconstruct them from the §3 narratives.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/projects` | Create a solar project / garden | GridOperator |
| GET | `/projects/{id}` | Get a project with all derived ledger fields | GridOperator, ProgramAdmin, Subscriber |
| POST | `/projects/{id}/carve-out-adjustments` | Adjust a project's low-income carve-out percentage | ProgramAdmin |
| GET | `/projects/{id}/carve-out-adjustments` | List carve-out adjustments for a project | GridOperator, ProgramAdmin |
| POST | `/subscribers` | Register a utility subscriber | ProgramAdmin |
| GET | `/subscribers/{id}` | Get a subscriber with churn risk and lifetime savings | GridOperator, ProgramAdmin, Subscriber |
| POST | `/enrollments` | Create a DRAFT enrollment | Subscriber, ProgramAdmin |
| GET | `/enrollments` | List enrollments, filterable by project, subscriber, or subscription | GridOperator, ProgramAdmin, Subscriber |
| GET | `/enrollments/{id}` | Get an enrollment | GridOperator, ProgramAdmin, Subscriber |
| POST | `/enrollments/{id}/submit` | Submit a DRAFT or resubmit a REJECTED enrollment | Subscriber |
| POST | `/enrollments/{id}/approve` | Approve a SUBMITTED enrollment | ProgramAdmin |
| POST | `/enrollments/{id}/reject` | Reject a SUBMITTED or APPROVED enrollment | ProgramAdmin |
| POST | `/enrollments/{id}/activate` | Activate an APPROVED enrollment into a subscription | ProgramAdmin |
| GET | `/subscriptions` | List subscriptions, filterable by several keys | GridOperator, ProgramAdmin, Subscriber |
| GET | `/subscriptions/{id}` | Get a subscription | GridOperator, ProgramAdmin, Subscriber |
| POST | `/subscriptions/{id}/suspend` | Suspend an ACTIVE subscription | ProgramAdmin |
| POST | `/subscriptions/{id}/resume` | Resume a SUSPENDED subscription | ProgramAdmin |
| POST | `/subscriptions/{id}/transfer` | Transfer a subscription's share to another subscriber | Subscriber |
| POST | `/subscriptions/{id}/cancel` | Cancel an ACTIVE or SUSPENDED subscription | Subscriber |
| POST | `/waitlist-entries` | Queue for capacity on a FULL project | Subscriber, ProgramAdmin |
| GET | `/waitlist-entries` | List waitlist entries, filterable by several keys | GridOperator, ProgramAdmin, Subscriber |
| GET | `/waitlist-entries/{id}` | Get a waitlist entry | GridOperator, ProgramAdmin, Subscriber |
| POST | `/waitlist-entries/{id}/withdraw` | Withdraw a QUEUED waitlist entry | Subscriber |
| POST | `/periods` | Open a billing period and distribute provisional allocations | GridOperator |
| GET | `/periods` | List billing periods, filterable by project | GridOperator, ProgramAdmin, Subscriber |
| GET | `/periods/{id}` | Get a billing period with computed ledger fields | GridOperator, ProgramAdmin, Subscriber |
| POST | `/periods/{id}/meter` | Set metered production and re-run the waterfall | GridOperator |
| POST | `/periods/{id}/reconcile` | Finalize allocations, credits, reconciliations, and mint RECs | GridOperator |
| POST | `/periods/{id}/true-up` | Sweep overproduction into rollover/forfeit | GridOperator |
| POST | `/periods/{id}/reopen` | Reopen a RECONCILED period back to METERED | GridOperator |
| POST | `/periods/{id}/close` | Close a TRUED_UP period | GridOperator |
| GET | `/allocations` | List allocations, filterable by period or subscription | GridOperator, ProgramAdmin, Subscriber |
| GET | `/allocations/{id}` | Get an allocation with provisional/final credit cents | GridOperator, ProgramAdmin, Subscriber |
| GET | `/reconciliations` | List reconciliations, filterable by several keys | GridOperator, ProgramAdmin, Subscriber |
| GET | `/reconciliations/{id}` | Get a reconciliation with savings and both status dimensions | GridOperator, ProgramAdmin, Subscriber |
| POST | `/reconciliations/{id}/issue` | Issue (post on-bill) a DRAFT reconciliation | GridOperator |
| POST | `/reconciliations/{id}/apply` | Apply an ISSUED reconciliation to lifetime savings | GridOperator |
| POST | `/reconciliations/{id}/dispute` | Raise a dispute on a reconciliation | Subscriber |
| POST | `/reconciliations/{id}/resolve-dispute` | Resolve a disputed reconciliation | ProgramAdmin |
| GET | `/rec-batches` | List REC batches, filterable by project or period | GridOperator, ProgramAdmin |
| GET | `/rec-batches/{id}` | Get a REC batch | GridOperator, ProgramAdmin |
| POST | `/rec-batches/{id}/allocate` | Earmark a MINTED REC batch for disposition | ProgramAdmin |
| POST | `/rec-batches/{id}/retire` | Retire an ALLOCATED REC batch to a beneficiary | ProgramAdmin |
| POST | `/rec-batches/{id}/transfer` | Transfer an ALLOCATED REC batch to a counterparty | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_VALIDATION | 422 |
| ERR_DUPLICATE_RESOURCE | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_PROJECT_VERSION | 412 |
| ERR_STALE_PERIOD_VERSION | 412 |
| ERR_PROJECT_FULL | 409 |
| ERR_CAPACITY_EXCEEDED | 409 |
| ERR_CARVE_OUT_EXCEEDED | 409 |
| ERR_USAGE_CAP_EXCEEDED | 409 |
| ERR_TRANSFER_JURISDICTION_MISMATCH | 409 |
| ERR_METER_READING_REQUIRED | 400 |
| ERR_DISPUTE_BLOCKS_APPLY | 409 |
| ERR_OPEN_DISPUTE_BLOCKS_CLOSE | 409 |
| ERR_RECON_ALREADY_APPLIED | 409 |
| ERR_REC_BENEFICIARY_REQUIRED | 400 |
| ERR_REC_COUNTERPARTY_REQUIRED | 400 |
| ERR_WAITLIST_NOT_QUEUED | 409 |
| ERR_IMMUTABLE_RESOURCE | 409 |
| ERR_PAGINATION_INVALID | 400 |
