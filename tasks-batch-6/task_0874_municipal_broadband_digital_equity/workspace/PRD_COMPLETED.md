# Municipal Broadband & Digital-Equity Program API — Product Requirements Document

## 1. Introduction

Municipalities that build and operate their own fiber networks carry a dual mandate: run a competitive retail broadband business, and close the digital divide with subsidized service and device distribution for low-income households — all while remaining accountable to the federal and state grant programs (notably BEAD) that fund the build. This API is the system of record that reconciles those obligations. It tracks fiber buildout at the census-block-group level, moves premises from planned to serviceable, sells tiered plans, schedules field installs, distributes customer-premises equipment and digital-equity devices, meters outages and issues SLA credits, invoices subscribers with subsidy discounts applied, and files grant reimbursement claims whose approval is gated by take-rate milestones and strict segregation of duties.

The domain is deliberately cross-cutting: a single service-area suspension ripples through subscriptions, install orders, and device inventory; an outage resolution fans out into SLA credits that reprice open invoices; and a grant claim moves money through committed and disbursed balances that must always reconcile back to the original award. This document specifies every entity, state transition, calculation, and validation the platform enforces. It is written for the engineering team that will implement the service, and it is the sole contract against which conformance is measured.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting invariants that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. A request missing either header, or carrying an unrecognized value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes nine roles, spelled exactly as follows: `ProgramAdmin`, `ComplianceAnalyst`, `ComplianceOfficer`, `CustomerCare`, `EligibilityWorker`, `Dispatcher`, `FieldTech`, `NocOperator`, and `Billing`. Each role owns a disjoint set of write operations described throughout §3, and every role may perform all read (GET) operations.

Eight of the nine roles carry an **opaque** identity: when `X-User-Role` is `ProgramAdmin`, `ComplianceAnalyst`, `ComplianceOfficer`, `CustomerCare`, `EligibilityWorker`, `Dispatcher`, `NocOperator`, or `Billing`, the `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record such an identifier where a workflow calls for it — for example, capturing the submitting analyst's `X-User-ID` as `submitted_by` on a grant claim — but it never compares that value to any entity's `id`. The one exception is `FieldTech`: when `X-User-Role` is `FieldTech`, `X-User-ID` is the `id` of the acting `Technician`. Ownership checks on install completion compare the install order's `technician_id` to `X-User-ID`, so a field technician may only complete installs assigned to them.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1, and no larger than 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are ordered by their `created_at` timestamp in ascending order, with ties broken by creation (insertion) order so the resulting sequence is deterministic. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and State Consistency

Every top-level resource carries a system-managed `id` formatted as a UUID, with no type prefix. Each also carries a `created_at` timestamp — an ISO 8601 UTC value with three fractional digits — recorded once at creation. All entities in this system are mutable and additionally carry an `updated_at` timestamp (same format as `created_at`) and an integer `version` that begins at 1 and increments by one on every mutation. Whenever the server mutates a resource — including automatic mutations the client did not directly request, such as a cascade or a lazily observed status change — it refreshes that resource's `updated_at` and increments its `version`.

The platform maintains immediate, cross-aggregate consistency. Several operations mutate more than one resource in a single logical step: suspending a service area cascades into its subscriptions, their install orders, and the devices those installs reserved; resolving an outage fans out into SLA credits and the invoices those credits reprice; approving or rejecting a grant claim moves money across a grant's balance accounts. Each secondary mutation independently updates the affected resource's `updated_at` and `version`. The specific cascade chains are described in §3 alongside the workflows that trigger them.

### 2.5. Existence Resolution and Validation Ordering

All validations are evaluated in a fixed priority order, so that a request failing several checks always surfaces the highest-priority failure. The order is: (1) authentication of the `X-User-ID` and `X-User-Role` headers, failing with `ERR_UNAUTHENTICATED`; (2) role authorization for the operation, failing with `ERR_UNAUTHORIZED`; (3) existence of every referenced resource, failing with the appropriate `ERR_*_NOT_FOUND`; (4) whether the target resource is in a state that permits the requested transition, failing with `ERR_INVALID_STATE`; (5) optimistic-concurrency version match, failing with `ERR_STALE_VERSION`; (6) business-referential preconditions; (7) segregation-of-duties; (8) temporal-window constraints; (9) business-constraint checks; and (10) fiscal sufficiency. The individual rules in bands 6 through 10 are detailed where their workflows live.

When a path names several resources, or a request body carries foreign-key ids, the server resolves them left-to-right in the order they appear, returning the not-found error for the first identifier that fails to resolve before considering any later identifier. Each entity has its own not-found code — `ERR_GRANT_NOT_FOUND`, `ERR_SERVICE_AREA_NOT_FOUND`, `ERR_SERVICE_PLAN_NOT_FOUND`, `ERR_SUBSIDY_PROGRAM_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_INSTALL_ORDER_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_OUTAGE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, and `ERR_GRANT_CLAIM_NOT_FOUND`. A request whose body omits a required field, carries a value of the wrong type, or supplies an invalid enumeration value is rejected with `ERR_VALIDATION`.

### 2.6. Monetary Amounts and Rounding

All monetary amounts are stored and returned as integer cents. Percentages such as take-rates and Federal-Poverty-Level ratios are computed to two decimal places. Wherever a computation is not already whole — SLA credits, per-subscriber reimbursement shares, take-rate percentages, and FPL percentages — the result is rounded using the round-half-up convention (a value exactly at the midpoint rounds up in magnitude). Invoice arithmetic operates purely on whole cents and therefore requires no rounding. Each calculation in §3 states the precise operands and the order in which they combine.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, each keyed to the current `version` of a parent resource the client must have observed.

Recording a payment against an invoice requires the caller to supply `expected_invoice_version` carrying the `version` of the target invoice as the client last read it. If the invoice's current `version` has advanced beyond that value — because a prior payment already updated the running total — the payment is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from posting a payment computed against a superseded balance.

Creating a grant claim against a grant requires the caller to supply `expected_grant_version` carrying the `version` of the target grant as the client last read it. Because every claim serializes against the grant's balance accounts, a create carrying a `version` that no longer matches the grant's current `version` reflects a view taken before another claim advanced the grant, and it is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field; operations not named here proceed without an OCC check.

### 2.8. The Logical Clock

The service maintains a logical clock that governs every time-dependent computation — certification expiry, outage downtime, and billing-period comparisons. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any set call it stays at that default rather than falling back to wall-clock time. An administrative test-driving capability moves the clock to a supplied `to_iso8601` instant. All references to "now" in this document mean the current value of this logical clock.

### 2.9. Take-Rate Accounting: Reported versus Verified

Take-rate is the fraction of a service area's serviceable premises that have taken service, and it is computed two ways from the same denominator — the area's `homes_passed`. The **reported** take-rate is the more optimistic projection: it counts subscriptions in the area whose `service_status` is either `PENDING_INSTALL` or `ACTIVE`, divides by `homes_passed`, multiplies by 100, and rounds half-up to two decimal places; it is exposed as `reported_take_rate_pct` on the service area. The **verified** take-rate counts only subscriptions whose `service_status` is `ACTIVE`, applies the same division, multiplication, and rounding, and is exposed as `verified_take_rate_pct`. Reported take-rate drives program projection and mapping; verified take-rate drives every milestone and reimbursement decision. Both are recomputed on demand whenever the area is read. When `homes_passed` is 0, both take-rates are reported as 0.00 rather than raising a division error.

### 2.10. Grant Fund Conservation

A grant's award is partitioned across three balance accounts at all times, and the partition is a hard invariant: `available_balance_cents` always equals `award_amount_cents` minus `committed_balance_cents` minus `disbursed_balance_cents`. Money never appears or disappears; it only moves between the committed, disbursed, and available accounts. Submitting a claim moves funds from available into committed; approving a claim moves those same funds from committed into disbursed, leaving available unchanged; rejecting a claim moves the committed funds back to available. Every one of these movements increments the grant's `version`. The exact accounting is specified in §3.7.

## 3. Business Logic & Workflows

### 3.1. Program Configuration: Grants, Areas, Plans, Subsidies, and Technicians

Program setup is the exclusive province of the `ProgramAdmin`. A grant is created with a `funding_source` (one of `BEAD`, `ARPA`, or `LOCAL`), a `program_name`, an `award_amount_cents` ceiling, a `match_required_pct` recording the local match obligation for the record, a `take_rate_milestone_pct` that a verified take-rate must reach or exceed to unlock the milestone, and an optional `take_rate_floor_pct` (defaulting to 0) naming the minimum verified take-rate below which a clawback would apply at administrative close. On creation the grant's `available_balance_cents` is seeded to the full `award_amount_cents`, while `committed_balance_cents` and `disbursed_balance_cents` both begin at 0, and `status` begins `ACTIVE`. A grant advances to `MILESTONE_MET` when a claim approval finds the covered take-rate has reached the milestone, and an `ACTIVE` or `MILESTONE_MET` grant may be closed administratively to `CLOSED`, after which no further claims are entertained; the `take_rate_floor_pct` governs whether a close triggers a clawback.

A service area is created against a parent grant via its `grant_id`, and carries a `name`, an FCC `census_block_group` identifier, a `homes_passed` count that serves as the take-rate denominator, and a `fiber_ready` flag defaulting to false. A newly created area is `PLANNED`. The administrator advances an area through its build lifecycle: `PLANNED` moves to `CONSTRUCTION` freely, and `CONSTRUCTION` moves to `SERVICEABLE` only when `fiber_ready` is true (otherwise the advance is rejected as an invalid transition). A `SERVICEABLE` area may be suspended, and a `SUSPENDED` area may be reinstated back to `SERVICEABLE`. Suspending an area, optionally annotated with a `reason`, triggers a three-level cascade: every subscription in the area whose `service_status` is `PENDING_INSTALL` or `ACTIVE` moves to `SUSPENDED` (level 1); for each such subscription, every install order still in `SCHEDULED` moves to `CANCELLED` (level 2); and for each cancelled install order, its reserved `ASSIGNED` `CPE_MODEM` device is released back to `IN_STOCK` with its subscription link cleared (level 3). Reinstating an area does not automatically reactivate its subscriptions — each must be handled individually.

Service plans, subsidy programs, and technicians round out configuration. A service plan is created with a `tier` (`BASIC`, `STANDARD`, or `PREMIUM`), a display `name`, `download_mbps` and `upload_mbps` speeds, a `monthly_price_cents` list price, and a contracted `sla_uptime_pct` such as 99.5. A subsidy program is created with a `name`, a `monthly_discount_cents` applied to an active enrollee's invoices, a one-time `device_benefit_cents` value for distribution devices, and an `eligibility_fpl_pct` ceiling. A technician is created with a `name`, a coverage `region`, and an optional `job_duration_minutes` fixed appointment length that defaults to 120 minutes; the technician's `status` begins `AVAILABLE` and may be moved to `INACTIVE` by deactivation, after which the technician can no longer be assigned to new install orders.

### 3.2. Subscribers and the Subscription Lifecycle

A `CustomerCare` operator registers a subscriber against a premises area via `service_area_id`, together with `full_name`, `email`, `service_address`, and `household_size`. A subscriber's `status` is always `ACTIVE`; the field exists for lifecycle symmetry. The same operator creates a subscription by supplying the `subscriber_id`, the `plan_id`, and the `service_area_id`. Creation requires that the named area currently be `SERVICEABLE`; otherwise it is rejected with `ERR_AREA_NOT_SERVICEABLE`. The referenced area must also match the subscriber's own area; a mismatch is rejected with `ERR_VALIDATION`. At creation the subscription snapshots the plan's price into its own `monthly_price_cents`, so later plan repricing never disturbs an existing subscription.

A subscription evolves along two independent axes. The **service axis**, `service_status`, begins `PENDING_INSTALL` and may become `ACTIVE`, `SUSPENDED`, or `CANCELLED`. Activation moves `PENDING_INSTALL` to `ACTIVE` and is permitted only when an install order for this subscription has reached `COMPLETED` (otherwise `ERR_INSTALL_NOT_COMPLETED`) and the subscription's area is `SERVICEABLE`; once active, the subscription counts toward its area's verified take-rate. A `CustomerCare` operator may suspend an `ACTIVE` subscription to `SUSPENDED`, and the area-suspension cascade of §3.1 drives both `ACTIVE` and `PENDING_INSTALL` subscriptions to `SUSPENDED` without operator action. Cancellation moves a subscription in `PENDING_INSTALL`, `ACTIVE`, or `SUSPENDED` to the terminal `CANCELLED` state. Cancelling from `PENDING_INSTALL` additionally cancels any `SCHEDULED` install order (with the compensating device unassignment) and voids any `ISSUED` invoice while reversing any applied SLA credit; cancelling from `ACTIVE` likewise voids any `ISSUED` invoice and reverses applied SLA credits; cancelling from `SUSPENDED` performs no further compensation and only moves the subscription to `CANCELLED`.

The **billing axis**, `billing_status`, evolves independently and begins `CURRENT`. It flips `CURRENT` to `PAST_DUE` when a new invoice is generated while a prior `ISSUED` invoice for the subscription has a `period_end` earlier than now and its `amount_paid_cents` remains below its `total_due_cents`. It returns `PAST_DUE` to `CURRENT` when a payment clears every outstanding invoice for the subscription.

### 3.3. Field Installation and Device Inventory

Install scheduling and device inventory belong to the `Dispatcher`, with completion reserved for the `FieldTech`. A dispatcher schedules an install by supplying the `subscription_id`, the `technician_id`, and a `scheduled_start_at` instant; the server derives `scheduled_end_at` by adding the technician's `job_duration_minutes` to the start. Scheduling requires the technician's `status` to be `AVAILABLE`, failing otherwise with `ERR_TECHNICIAN_INACTIVE`. The proposed window must not overlap any other `SCHEDULED` install for the same technician; overlap is judged on half-open intervals `[start, end)`, so an install that begins exactly when another ends is allowed, and a genuine overlap is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`. A new install begins in `SCHEDULED`.

A `SCHEDULED` install may be rescheduled to a new `scheduled_start_at`; this is a self-loop that keeps the order `SCHEDULED`, re-derives `scheduled_end_at`, increments `reschedule_count` by one, and re-applies the same half-open overlap check against the technician's other `SCHEDULED` orders. A dispatcher may also cancel a `SCHEDULED` install to `CANCELLED`, which compensatingly returns any `ASSIGNED` `CPE_MODEM` device reserved for that subscription to `IN_STOCK`. The field technician completes their own `SCHEDULED` install: completion is allowed only when the acting `X-User-ID` equals the order's `technician_id` and the subscription's `service_status` is still `PENDING_INSTALL`. If a `device_id` is supplied at completion, that device — an `ASSIGNED` `CPE_MODEM` — moves to `DEPLOYED`; the device need only exist and is moved to `DEPLOYED` unconditionally, without re-validating its `device_class` or current status. Completion is what enables the subscription to be activated.

Devices are inventory items created with a `device_class` (`CPE_MODEM`, `TABLET`, `LAPTOP`, or `HOTSPOT`), a `model`, a unique `serial_number`, and a `value_cents` book value; a new device is `IN_STOCK`. Assignment requires the device to be `IN_STOCK` and exactly one of `subscription_id` or `enrollment_id` to be supplied — neither zero nor both — failing otherwise with `ERR_DEVICE_NOT_AVAILABLE`; assignment sets the corresponding link and moves the device to `ASSIGNED`. A `CPE_MODEM` bound to a subscription deploys at install completion; a distribution device bound to an enrollment deploys on delivery. Returning a device restocks it: an `ASSIGNED` device returns to `IN_STOCK` with its `subscription_id` and `enrollment_id` links cleared so total inventory is conserved, while a `DEPLOYED` device moves to the terminal-in-practice `RETURNED` state, which is also where an enrollment termination sends a deployed distribution device.

### 3.4. Low-Income Enrollment and Recertification

The `EligibilityWorker` runs the digital-equity enrollment program. An application is created with the `subscriber_id`, the `subsidy_program_id`, the household's `household_size`, and its `annual_income_cents`. On creation the server computes the applicant's Federal-Poverty-Level ratio, `fpl_pct`: it divides `annual_income_cents` by the annual FPL base for the given household size, multiplies by 100, and rounds half-up to two decimal places. The FPL base amounts, in cents, are 1,506,000 for a household of 1, 2,034,000 for 2, 2,562,000 for 3, 3,090,000 for 4, and 3,618,000 for 5. A `household_size` outside the supported 1–5 range is rejected with `ERR_VALIDATION`. A new enrollment begins `SUBMITTED`, with `certification_expires_at` null until it is activated.

Verification decides eligibility. The applicant is eligible when the computed `fpl_pct` is at or below the subsidy program's `eligibility_fpl_pct` ceiling — the boundary is inclusive. An eligible verification also requires that the subscriber have no other `ACTIVE` enrollment, failing otherwise with `ERR_DUPLICATE_ACTIVE_ENROLLMENT`; when it succeeds, the enrollment moves `SUBMITTED` to `ACTIVE`, its `certification_expires_at` is set to now plus 365 days, and the subscriber's subsequent invoices begin receiving the subsidy discount. An ineligible verification — `fpl_pct` strictly above the ceiling — moves the enrollment `SUBMITTED` to the terminal `DENIED`.

Certification is a recurring cycle. Once the logical clock reaches an active enrollment's `certification_expires_at`, the enrollment is observed as `RECERT_DUE` lazily — any read of the enrollment or any recertify attempt sees it in `RECERT_DUE` without a separate transition call. Recertification recomputes `fpl_pct` (optionally against a fresh `annual_income_cents` supplied at recertify time, otherwise the enrollment's existing income). If the recomputed ratio is still at or below the ceiling, the enrollment returns `RECERT_DUE` to `ACTIVE` and `certification_expires_at` is reset to now plus 365 days, closing the loop. If it is no longer eligible, or the worker explicitly terminates, the enrollment moves to the terminal `TERMINATED`. Termination may also be applied directly to an `ACTIVE` enrollment and accepts an optional `reason`. Either way, terminating an enrollment cascades: the subscriber loses the subsidy discount on future invoices, and any `DEPLOYED` distribution device tied to that enrollment via its `enrollment_id` is moved to `RETURNED`.

### 3.5. Billing and Invoicing

The `Billing` role generates invoices and records payments. An invoice is generated for a subscription over a period defined by `period_start` (inclusive) and `period_end` (exclusive); `period_end` must be strictly later than `period_start`, failing otherwise with `ERR_PERIOD_INVALID`. Invoice amounts are computed entirely in whole cents in a pinned order. The `base_amount_cents` is a snapshot of the subscription's `monthly_price_cents`. The `subsidy_discount_cents` is the subsidy first: if the subscriber has an `ACTIVE` enrollment, it is the smaller of that enrollment's subsidy program `monthly_discount_cents` and the base amount; if there is no `ACTIVE` enrollment it is 0. Subtracting the subsidy from the base yields the post-subsidy net. The `sla_credit_cents` applied to the invoice is then the smaller of the sum of SLA-credit amounts already applied to this invoice and that post-subsidy net, so the credit can never drive the bill below zero. Finally `total_due_cents` is the base amount minus the subsidy discount minus the applied SLA credit — subsidy first, then SLA credit on the post-subsidy net. A freshly generated invoice is `ISSUED` with `amount_paid_cents` at 0. Generating an invoice may flip the subscription's `billing_status` from `CURRENT` to `PAST_DUE` under the condition described in §3.2.

A payment carries an `amount_cents` and the OCC field `expected_invoice_version`, and is accepted only against an `ISSUED` invoice — a payment against a `PAID` or `VOID` invoice is rejected with `ERR_INVOICE_NOT_PAYABLE`. Once the version check of §2.7 passes, the payment adds `amount_cents` to the invoice's `amount_paid_cents` and increments the invoice's `version`. When cumulative `amount_paid_cents` reaches or exceeds `total_due_cents`, the invoice moves `ISSUED` to `PAID`; an SLA credit that zeroes the balance drives the same transition. When a payment settles the last outstanding invoice for a subscription, the subscription's `billing_status` returns to `CURRENT`. An invoice may also move `ISSUED` to `VOID` as a cascade of subscription cancellation, at which point any SLA credit applied to it is reversed.

### 3.6. Outages and SLA Credits

The `NocOperator` reports and resolves outages. An outage is reported against a `service_area_id` with a `started_at` instant and a `severity` of `PARTIAL` or `FULL`; a new outage must not fall within 60 minutes of an existing `OPEN` outage on the same area, where the window is the existing outage's interval extended by that buffer on each side, failing otherwise with `ERR_OUTAGE_OVERLAP`. Because an `OPEN` outage has no `ended_at`, its window collapses to its `started_at` alone: the check rejects the new outage when its `started_at` falls anywhere in the inclusive span from the existing outage's `started_at` minus 60 minutes through its `started_at` plus 60 minutes. On report, the outage snapshots `affected_subscription_count` as the number of `ACTIVE` subscriptions in the area and computes a provisional `estimated_credit_total_cents`. The outage begins `OPEN`, with `ended_at` null until resolution.

An SLA credit for one subscription and one outage is `round_half_up(subscription.monthly_price_cents * downtime_minutes / 43200)`, where 43,200 is the number of minutes in the standard monthly billing period. This credit is computed in two variants that differ only in how downtime is measured. The **provisional** variant is computed at report time while the outage is `OPEN`: downtime in minutes is now minus `started_at`, floored to whole minutes and treated as 0 if `started_at` is in the future, and each affected subscription's provisional credit is summed into the outage's `estimated_credit_total_cents`. The **final** variant is computed at resolution: downtime in minutes is `ended_at` minus `started_at`.

Resolving an outage requires an `ended_at` that is supplied and strictly later than `started_at`, failing otherwise with `ERR_OUTAGE_NOT_ENDED`; on success the outage moves `OPEN` to `RESOLVED`. Resolution runs a three-level cascade. For each `ACTIVE` subscription in the area, the server creates an SLA credit in `PENDING` whose `downtime_minutes` is the final whole-minute downtime and whose `credit_cents` is the final-variant amount, linking it to the subscription via `subscription_id` and to the outage via `outage_id`; the sum of these is recorded on the outage's `final_credit_total_cents` (level 1). Each new credit is then `APPLIED` to that subscription's latest `ISSUED` invoice: the credit's `applied_invoice_id` is set to that invoice, the invoice's `sla_credit_cents` and `total_due_cents` are recomputed per §3.5, and the credit's `status` becomes `APPLIED` (level 2); if the subscription has no `ISSUED` invoice, the credit remains `PENDING` with a null `applied_invoice_id`. Finally, if a recomputed invoice's `total_due_cents` is at or below its `amount_paid_cents`, the invoice moves to `PAID`, and if every invoice for the subscription is then settled, the subscription's `billing_status` returns to `CURRENT` (level 3). An SLA credit that is later reversed — for instance when its invoice is voided by a subscription cancellation — moves to `REVERSED`. SLA credits are discovery-only resources: they are read individually or listed, never created directly.

### 3.7. Grant Claims and BEAD Compliance

Grant reimbursement flows through a claim whose duties are strictly separated between the `ComplianceAnalyst`, who prepares and submits, and the `ComplianceOfficer`, who approves or rejects — the same person may never both submit and decide a claim. A claim is created against a grant by an analyst, who supplies `claim_period_start`, `claim_period_end` (which must be later than the start, otherwise `ERR_PERIOD_INVALID`), the array of covered `service_area_ids`, and the OCC field `expected_grant_version`. Creation computes the claim's `amount_claimed_cents` and increments the grant's `version` by one. The claim's `submitted_by`, `reported_take_rate_pct`, and `subsidized_subscriber_count` are system-maintained, and a new claim begins `DRAFT`.

The reimbursement amount aggregates a fixed federal share of the subsidy across qualifying households. A qualifying subscriber is an `ACTIVE` subscription that also has an `ACTIVE` enrollment in one of the covered, `SERVICEABLE` areas. Each such subscriber contributes a per-subscriber share equal to that enrollee's active subsidy `monthly_discount_cents` multiplied by 33.34 percent, rounded half-up to whole cents. The rounding order is pinned: round each subscriber's share to whole cents first, then sum the rounded shares into `amount_claimed_cents` — summing raw shares and rounding once at the end is not used and would produce a different figure. The claim also records `subsidized_subscriber_count` as the count of those qualifying subscribers.

Submission moves the claim `DRAFT` to `SUBMITTED` and is performed by the analyst, whose `X-User-ID` is captured as `submitted_by`. Submission requires that every area in `service_area_ids` be `SERVICEABLE` (otherwise `ERR_AREA_NOT_SERVICEABLE`) and that the recomputed `amount_claimed_cents` not exceed the grant's `available_balance_cents` (otherwise `ERR_INSUFFICIENT_GRANT_FUNDS`). On success it commits funds — the grant's `committed_balance_cents` increases by `amount_claimed_cents`, and `available_balance_cents` is recomputed so the award partition of §2.10 is preserved — and increments the grant's `version`. The claim also captures its aggregate verified take-rate across the covered areas into `reported_take_rate_pct` at submit time.

An officer then decides the `SUBMITTED` claim, and the acting `X-User-ID` must differ from `submitted_by`, failing otherwise with `ERR_SEGREGATION_OF_DUTIES`. Approval moves the claim to the terminal `APPROVED` and disburses: `committed_balance_cents` decreases by `amount_claimed_cents` while `disbursed_balance_cents` increases by the same amount, leaving `available_balance_cents` unchanged and money conserved. Approval also runs the milestone check: the aggregate verified take-rate over the covered areas is the sum of their active-subscription counts divided by the sum of their `homes_passed`, times 100, rounded half-up to two decimal places; if that aggregate is at or above the grant's `take_rate_milestone_pct`, the grant moves to `MILESTONE_MET`. Rejection, optionally annotated with a `reason`, moves the claim to the terminal `REJECTED` and compensatingly releases the committed funds: `committed_balance_cents` decreases by `amount_claimed_cents` and `available_balance_cents` is restored, again preserving the partition.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions and payments — return `200 OK`. All list and single-fetch reads return `200 OK`. The request body, response shape, and side effects of each endpoint are specified in the §3 narratives above; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/grants` | Create a grant | ProgramAdmin |
| GET | `/grants/{id}` | Get a grant | Any |
| POST | `/grants/{id}/claims` | Create a grant claim (OCC on grant) | ComplianceAnalyst |
| GET | `/grants/{id}/claims` | List claims for a grant | Any |
| POST | `/service-areas` | Create a service area | ProgramAdmin |
| GET | `/service-areas/{id}` | Get a service area with take-rate | Any |
| GET | `/service-areas` | List service areas | Any |
| POST | `/service-areas/{id}/advance` | Advance build state | ProgramAdmin |
| POST | `/service-areas/{id}/suspend` | Suspend an area (cascade) | ProgramAdmin |
| POST | `/service-areas/{id}/reinstate` | Reinstate a suspended area | ProgramAdmin |
| POST | `/service-plans` | Create a service plan | ProgramAdmin |
| GET | `/service-plans/{id}` | Get a service plan | Any |
| POST | `/subsidy-programs` | Create a subsidy program | ProgramAdmin |
| GET | `/subsidy-programs/{id}` | Get a subsidy program | Any |
| POST | `/subscribers` | Create a subscriber | CustomerCare |
| GET | `/subscribers/{id}` | Get a subscriber | Any |
| GET | `/subscribers` | List subscribers | Any |
| POST | `/subscriptions` | Create a subscription | CustomerCare |
| GET | `/subscriptions/{id}` | Get a subscription | Any |
| GET | `/subscriptions` | List subscriptions | Any |
| POST | `/subscriptions/{id}/activate` | Activate a subscription | CustomerCare |
| POST | `/subscriptions/{id}/suspend` | Suspend a subscription | CustomerCare |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription (cascade) | CustomerCare |
| POST | `/subscriptions/{id}/invoices` | Generate an invoice for a period | Billing |
| GET | `/subscriptions/{id}/invoices` | List invoices for a subscription | Any |
| GET | `/invoices/{id}` | Get an invoice | Any |
| POST | `/invoices/{id}/payments` | Record a payment (OCC on invoice) | Billing |
| POST | `/enrollments` | Create an enrollment application | EligibilityWorker |
| GET | `/enrollments/{id}` | Get an enrollment | Any |
| GET | `/enrollments` | List enrollments | Any |
| POST | `/enrollments/{id}/verify` | Verify eligibility | EligibilityWorker |
| POST | `/enrollments/{id}/recertify` | Recertify an enrollment | EligibilityWorker |
| POST | `/enrollments/{id}/terminate` | Terminate an enrollment (cascade) | EligibilityWorker |
| POST | `/technicians` | Create a technician | ProgramAdmin |
| GET | `/technicians/{id}` | Get a technician | Any |
| POST | `/technicians/{id}/deactivate` | Deactivate a technician | ProgramAdmin |
| POST | `/install-orders` | Schedule an install (overlap-checked) | Dispatcher |
| GET | `/install-orders/{id}` | Get an install order | Any |
| GET | `/install-orders` | List install orders | Any |
| POST | `/install-orders/{id}/reschedule` | Reschedule an install (overlap-checked) | Dispatcher |
| POST | `/install-orders/{id}/complete` | Complete an install | FieldTech |
| POST | `/install-orders/{id}/cancel` | Cancel an install (compensating) | Dispatcher |
| POST | `/devices` | Create a device inventory item | Dispatcher |
| GET | `/devices/{id}` | Get a device | Any |
| GET | `/devices` | List devices | Any |
| POST | `/devices/{id}/assign` | Assign a device | Dispatcher |
| POST | `/devices/{id}/return` | Return/restock a device (compensating) | Dispatcher |
| POST | `/outages` | Report an outage (overlap/buffer-checked) | NocOperator |
| GET | `/outages/{id}` | Get an outage | Any |
| GET | `/outages` | List outages | Any |
| POST | `/outages/{id}/resolve` | Resolve an outage (cascade credits) | NocOperator |
| GET | `/sla-credits/{id}` | Get an SLA credit | Any |
| GET | `/sla-credits` | List SLA credits | Any |
| GET | `/grant-claims/{id}` | Get a grant claim | Any |
| POST | `/grant-claims/{id}/submit` | Submit a claim (commits funds) | ComplianceAnalyst |
| POST | `/grant-claims/{id}/approve` | Approve a claim (SoD, disburse) | ComplianceOfficer |
| POST | `/grant-claims/{id}/reject` | Reject a claim (SoD, release) | ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_GRANT_NOT_FOUND` | 404 |
| `ERR_SERVICE_AREA_NOT_FOUND` | 404 |
| `ERR_SERVICE_PLAN_NOT_FOUND` | 404 |
| `ERR_SUBSIDY_PROGRAM_NOT_FOUND` | 404 |
| `ERR_SUBSCRIBER_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 |
| `ERR_INSTALL_ORDER_NOT_FOUND` | 404 |
| `ERR_DEVICE_NOT_FOUND` | 404 |
| `ERR_OUTAGE_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_GRANT_CLAIM_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_AREA_NOT_SERVICEABLE` | 409 |
| `ERR_TECHNICIAN_INACTIVE` | 409 |
| `ERR_INSTALL_NOT_COMPLETED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_TECHNICIAN_DOUBLE_BOOKED` | 409 |
| `ERR_OUTAGE_OVERLAP` | 409 |
| `ERR_PERIOD_INVALID` | 422 |
| `ERR_OUTAGE_NOT_ENDED` | 422 |
| `ERR_DEVICE_NOT_AVAILABLE` | 409 |
| `ERR_DUPLICATE_ACTIVE_ENROLLMENT` | 409 |
| `ERR_INVOICE_NOT_PAYABLE` | 409 |
| `ERR_INSUFFICIENT_GRANT_FUNDS` | 409 |
