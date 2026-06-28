# Direct Primary Care API — Product Requirements Document

## 1. Introduction

Direct Primary Care (DPC), often marketed as a concierge membership, replaces the per-visit fee-for-service model with a flat recurring membership that buys a patient unhurried, same-day access to a personal primary care provider. This document specifies the API for a DPC practice platform: members enroll and pay a monthly or prepaid-annual fee, are assigned a panel-managed primary care provider (PCP), book same-day and virtual visits, receive an annual physical and a longitudinal care plan, exchange after-hours messages, and obtain specialist referrals. Employers may sponsor seats on behalf of their staff, covering all or part of the membership fee.

The platform must reconcile two financial worlds at once. Membership dues flow on a recurring billing cycle with grace periods, late fees, proration on cancellation, and employer cost-sharing; clinical charges, by contrast, are split between what the DPC membership covers outright and what is routed to a member's third-party insurance. Because money, panel capacity, scheduling slots, and clinical lifecycles all mutate one another, the system treats every cross-resource effect as immediate and deterministic. Several operations are guarded against lost updates through optimistic concurrency control, and a small set of administrative test-driving endpoints lets operators advance a logical clock and run periodic billing and expiry sweeps.

This specification is organized so that global, system-wide contracts appear first, followed by the detailed business logic and workflows, and finally the consolidated endpoint and error catalogues. Engineers should read Section 3 in full before implementing any single endpoint, because the rules governing one operation are frequently introduced alongside the workflow they serve rather than next to the endpoint that triggers them.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request other than the open self-service and bootstrap endpoints must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the call is made. When either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes five roles, spelled exactly as follows: `PlatformAdmin`, `Provider`, `Member`, `Employer`, and `Anonymous`. When a caller presents a valid role but that role is not permitted to perform the requested operation — or presents an identity that does not own the targeted resource — the request is rejected with `ERR_FORBIDDEN`.

Three of these roles are entity-backed, meaning the value carried in `X-User-ID` is the `id` of a persisted resource and ownership checks compare a resource's foreign-key reference to that identifier. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on any clinical resource compare that resource's `provider_id` (or, for members, `assigned_provider_id`) to `X-User-ID`. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership of a visit, membership, message thread, invoice, payment, referral, or care plan is established by comparing that resource's `member_id` to `X-User-ID`. When `X-User-Role` is `Employer`, `X-User-ID` is the `id` of the acting `Employer`; ownership of a seat or sponsorship is established by comparing the `employer_id` to `X-User-ID`.

The remaining two roles are opaque. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the platform administrator operates practice configuration, provider and employer setup, PCP assignment, billing runs, and the logical clock, and the server does not compare its `X-User-ID` to any entity's `id`. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise an opaque, untracked identifier; the anonymous role exists solely so an unauthenticated visitor can self-register as a member, and member self-registration is the only operation it may perform.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the server's logical clock (§2.9) rather than wall-clock time.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, all list responses are sorted by the resource's creation timestamp, `created_at`, in ascending order; resources sharing an identical `created_at` (common because creations read the same logical clock) are then ordered by the sequence in which they were persisted, so the ordering is fully deterministic. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the count of all matching resources before pagination and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties and the Identity Model

Most resources in this system are first-class entities that carry a uniform set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at creation while `updated_at` advances on every mutation. The `version` is an integer that starts at 1 when the resource is created and increments by one on each mutation; it underpins the optimistic concurrency mechanism described in §2.6.

`Payment` is the single exception. A payment is an immutable record of a charge attempt and therefore carries only `id` and `created_at`; it has neither an `updated_at` nor a `version` field, because once written it is never modified.

Resources reference one another by foreign-key identifiers — for example a `Provider` carries the `practice_id` of its parent practice, a `Member` carries a `practice_id`, and most clinical and financial resources carry a `member_id`. These references are validated for existence on every write, and ownership is enforced against the acting identity per §2.1.

### 2.5. Hierarchical Consistency, Cascades, and Nested Retrieval

Because clinical scheduling, panel capacity, employer sponsorship, and billing are interdependent, a single operation routinely mutates more than one resource. Whenever a member's `membership_status` changes, the system recomputes the assigned provider's `active_panel_count` and re-derives `panel_load_bucket`; whenever a visit is booked or released, the owning slot's `booked_count` and `slot_state` are recomputed; whenever a seat is occupied or released, the employer's `occupied_seat_count` is recomputed. Each such secondary mutation independently advances the affected resource's `updated_at` and increments its `version`. The specific cascades are described in the workflow narratives of Section 3, and they must all fire as part of the triggering operation rather than being deferred.

For requests that address a nested resource, path identifiers are validated strictly left-to-right. A request whose path names an employer and then a seat under that employer first confirms the employer exists; only then is the seat resolved. The first identifier in the path that does not resolve to an existing resource causes immediate rejection with `ERR_NOT_FOUND`, before any deeper identifier or any business rule is evaluated.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded against lost updates by optimistic concurrency control, because under the product rules a second writer can legitimately succeed against the same parent and the conflict is therefore not reducible to a state precondition.

Booking a visit must carry `expected_slot_version`, the `version` of the target `VisitSlot` the client last observed. If another booking has advanced that slot's `version` since the client read it — for example, by consuming the last remaining in-person capacity or a virtual seat — the booking is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's view of the slot's `booked_count` is stale. Likewise, occupying a sponsored seat must carry `expected_employer_version`, the `version` of the target `Employer` the client last observed; if another occupy call has advanced the employer's `version` since the client read it (for instance, by filling the last open seat), the occupy is rejected with `ERR_STALE_VERSION` (HTTP 412). These two endpoints are the only operations that accept a version field; no other endpoint takes one, and where present the version field is required, not optional.

### 2.7. The Insurance-vs-DPC Billing Split

The defining financial principle of the platform is that clinical charges are partitioned by whether the service is covered by the DPC membership. Each practice configures `dpc_covered_service_codes`, the set of service codes a member owes nothing to the practice for. Any service line whose code is not in that set is a non-DPC charge. For a member without third-party insurance, the practice bills the full non-DPC charge directly to the member. For an insured member, those non-DPC lines are routed to insurance and the member owes only a coinsurance share governed by the practice's `insurance_coinsurance_pct`. The exact arithmetic, including where rounding occurs, is specified in §3.7.

### 2.8. Monetary Precision and Counts

All monetary amounts are stored and transmitted as integer cents. Wherever a calculation produces a fractional cent, the result is rounded half up to the nearest whole cent. Each calculation below states the precise step at which rounding is applied; rounding is performed exactly once at each named rounding step and never compounded line-by-line where the specification calls for a single aggregate rounding. Panel sizes, seat counts, booked counts, goal counts, and revision numbers are integer quantities and are never rounded because they are never fractional.

### 2.9. The Logical Clock and Scheduled Sweeps

All deadline, expiry, grace-period, and billing-period computations read a server-controlled logical clock rather than wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and until an operator sets it, it stays at that value and never falls back to real time. A platform administrator may advance the clock to any instant. Time-driven state changes that are not triggered by a direct client action — membership suspension after grace, referral expiry, and message-thread escalation — are applied by a periodic sweep that an administrator runs on demand; their exact triggers and effects appear in the relevant Section 3 workflows.

## 3. Business Logic & Workflows

### 3.1. Practice Configuration and Provider Setup

A `PlatformAdmin` bootstraps the system by creating a `Practice`, the configuration root. A practice is created with a display `name`, a soft `panel_target` and a hard `panel_hard_cap` that govern panel sizing, the standard individual `monthly_fee_cents`, the list of `dpc_covered_service_codes`, and several billing parameters. The `panel_target` must be greater than zero, and `panel_hard_cap` must be at least as large as `panel_target`; a `panel_hard_cap` below `panel_target` is rejected with `ERR_VALIDATION`. The `monthly_fee_cents` must be greater than zero. The optional `annual_fee_discount_pct` is the fractional discount applied to the prepaid annual plan and defaults to 0.15 (fifteen percent); it must be at least zero and strictly less than one. The optional `insurance_coinsurance_pct` is the member's coinsurance share on insurance-billed lines and defaults to 0.20; it must be at least zero and strictly less than one. The optional flat `late_fee_cents` added when a charge lapses defaults to 2500 and must be at least zero. The optional `grace_period_days`, the number of days a past-due membership may linger before auto-suspension, defaults to 14 and must be at least zero. Practices, like all configuration entities, are readable by every role.

The administrator then registers each `Provider` under a practice, supplying the parent `practice_id`, the provider's `full_name`, and an `npi` (National Provider Identifier) that must be unique within the practice. Two optional fields tune panel behavior: `panel_capacity`, a per-provider override hard cap that defaults to null (meaning the practice's `panel_hard_cap` applies), which must be null or greater than zero; and `accepting_new_members`, which defaults to true and, when false, excludes the provider from automatic assignment candidate pools. At registration a provider's computed `active_panel_count` is initialized to zero and its computed `panel_load_bucket` is initialized to `UNDER_TARGET`.

A provider's **effective cap** is its own `panel_capacity` when that is set, and otherwise the practice's `panel_hard_cap`. The `active_panel_count` is the number of members assigned to the provider whose `membership_status` is either `ACTIVE` or `PAST_DUE`; members in `PENDING_PAYMENT`, `SUSPENDED`, or `CANCELLED` do not count toward it. This count is recomputed on every assignment, unassignment, suspension, and reinstatement. The derived `panel_load_bucket` is `UNDER_TARGET` while `active_panel_count` is below the practice's `panel_target`, `AT_TARGET` while `active_panel_count` is at least the `panel_target` but below the effective cap, and `FULL` once `active_panel_count` equals the effective cap.

### 3.2. Employer Sponsorship and Seat Allocation

An employer is registered under a practice by a `PlatformAdmin` with the parent `practice_id`, a `company_name`, a `sponsored_seat_limit` (the maximum number of concurrently occupied sponsored seats, which must be greater than zero), and an optional `sponsorship_pct`. The `sponsorship_pct` is the fraction of each sponsored member's monthly fee the employer covers; it defaults to 1.0 and must be greater than zero and at most one — a value outside that range is rejected with `ERR_VALIDATION`. The employer's computed `occupied_seat_count` starts at zero.

Either a `PlatformAdmin` or the owning `Employer` may allocate a new seat under an employer; allocation creates an `EmployerSeat` whose `seat_status` begins as `OPEN` and whose `member_id` is null. A seat's `seat_status` moves among three values: `OPEN` (allocated but unfilled), `OCCUPIED` (currently sponsoring a member), and `RELEASED` (returned to the pool, terminal). Each seat references its `employer_id`.

Occupying a seat assigns a member to an `OPEN` seat and is the operation guarded by optimistic concurrency on the employer described in §2.6; the request supplies the `member_id` to seat and the `expected_employer_version`. Before the seat may be occupied, the employer must have an `OPEN` seat and its `occupied_seat_count` must be strictly below `sponsored_seat_limit`; if neither condition holds the request is rejected with `ERR_SEAT_LIMIT_REACHED`. On success the seat's `seat_status` becomes `OCCUPIED` and its `member_id` is set, the member's `Membership` records the `employer_seat_id`, and the member's monthly share is recomputed (per §3.7) to reflect the employer's sponsorship. The employer's `occupied_seat_count` is incremented and the employer's `version` is incremented by one. Releasing a seat — which happens as a cascade of membership cancellation or suspension, never as a direct seat operation — moves the seat to `RELEASED`, clears its `member_id`, and recomputes `occupied_seat_count`.

### 3.3. Member Enrollment and the Membership Lifecycle

Enrollment begins when a prospective patient self-registers through the open, `Anonymous`-only registration capability. The caller supplies the `practice_id`, a contact `email` that must be unique within the practice, the member's `full_name`, an optional `plan_type` that defaults to `MONTHLY`, and an optional `has_insurance` flag that defaults to false. Registration creates the `Member` in `PENDING_PAYMENT` status together with its 1:1 `Membership` in a single call. The membership snapshots the chosen `plan_type` and the practice's `monthly_fee_cents` into its own `monthly_fee_cents`, leaves `current_period_start` unset for now, and computes the member's `member_share_cents` as an unsponsored figure. A member's `plan_type` is one of `MONTHLY` or `ANNUAL_PREPAID`. The member also carries a computed `wallet_credit_cents` account credit (from refunds and overpayments, applied before any card is charged and never allowed to go negative, defaulting to zero) and a computed `annual_physical_due_on` date (defaulting to null). The member's `assigned_provider_id` is system-managed and begins null.

Before a member's first activating charge can succeed, a PCP must be assigned. A `PlatformAdmin` assigns a PCP by supplying a `mode`. When `mode` is `MANUAL`, the administrator pins a specific `provider_id`. When `mode` is `AUTO`, the system runs the panel-assignment selector described in §3.4 to choose a provider. Assignment sets the member's `assigned_provider_id`; if the member is already `ACTIVE` or `PAST_DUE`, the selected provider's `active_panel_count` and `panel_load_bucket` are recomputed to reflect the new panel member, and when this reassigns the member away from a different previously-assigned provider that prior provider's `active_panel_count` and `panel_load_bucket` are recomputed as well. Attempting the first activating charge while `assigned_provider_id` is still null is rejected with `ERR_PCP_REQUIRED`.

The `membership_status` field is the heart of the lifecycle and moves among `PENDING_PAYMENT`, `ACTIVE`, `PAST_DUE`, `SUSPENDED`, and `CANCELLED`, with `CANCELLED` terminal. Activation is driven by a successful membership-fee charge (see §3.8). Moving a member from `PENDING_PAYMENT` to `ACTIVE` requires that `assigned_provider_id` is non-null and that the successful payment's `amount_cents` equals the membership's `member_share_cents`; on success the membership's `current_period_start` is set to the clock's current instant, `current_period_end` is recomputed, and the assigned provider's `active_panel_count` and `panel_load_bucket` are recomputed because the newly active member now joins the active panel.

A member that is `ACTIVE` slips to `PAST_DUE` when a membership-fee charge fails at period rollover — that is, when the logical clock has reached or passed the membership's `current_period_end` and the charge's `outcome` is `FAILED`. Entering `PAST_DUE` stamps `past_due_since` with the current instant and adds the practice's `late_fee_cents` to the member share owed on the next charge. From `PAST_DUE`, a successful membership-fee charge returns the member to `ACTIVE`, provided the membership is currently `PAST_DUE` and the clock is still before `past_due_since` plus the practice's `grace_period_days`; reinstatement clears `past_due_since` and advances both `current_period_start` and `current_period_end` by one period. If the grace window has instead elapsed — the clock has reached or passed `past_due_since` plus `grace_period_days` days — the periodic sweep moves the membership from `PAST_DUE` to `SUSPENDED`. A suspended member leaves the active panel, so the assigned provider's `active_panel_count` and `panel_load_bucket` are recomputed; additionally, every one of that member's visits still in `BOOKED` or `CHECKED_IN` clinical status is cancelled as a cross-entity cascade, and each cancelled visit decrements its slot's `booked_count` and recomputes that slot's `slot_state`.

A `SUSPENDED` member can be reinstated to `ACTIVE` by a successful membership-fee charge, but only when the membership is `SUSPENDED` and the assigned provider's panel still has room — that is, the provider's `active_panel_count` is strictly below its effective cap, since reinstatement re-occupies a panel slot. Reinstatement clears `past_due_since`, advances the billing period, and recomputes the provider's `active_panel_count` and `panel_load_bucket` as the member re-enters the active panel.

A `Member` may cancel their own membership, and the consequences depend on the status from which they cancel. Cancelling from `ACTIVE` issues a prorated wallet credit (computed per §3.9) into `wallet_credit_cents`; if the membership has a non-null `employer_seat_id`, that seat is set to `RELEASED`, its `member_id` is cleared, and the employer's `occupied_seat_count` is recomputed; the assigned provider's `active_panel_count` and `panel_load_bucket` are recomputed as the member leaves the active panel; and every visit of that member in `BOOKED` or `CHECKED_IN` status is cancelled, each decrementing its slot's `booked_count` and recomputing `slot_state`. Cancelling from `PAST_DUE` produces no proration credit, because the dues have already lapsed, but still releases any employer seat (recomputing `occupied_seat_count`) and recomputes the provider's `active_panel_count` and `panel_load_bucket`. Cancelling from `SUSPENDED` likewise grants no proration and, if an `employer_seat_id` is present, releases that seat and recomputes `occupied_seat_count`. All three cancellation paths drive `membership_status` to `CANCELLED`.

The membership record itself tracks the snapshot `plan_type`, the snapshot `monthly_fee_cents`, the `employer_seat_id` (non-null only while sponsored), the computed `member_share_cents`, the `current_period_start`, the computed `current_period_end`, and `past_due_since` (null when the membership is not past due). The `current_period_end` is `current_period_start` plus 30 days for a `MONTHLY` plan and plus 365 days for an `ANNUAL_PREPAID` plan.

### 3.4. Panel Assignment Selection

When a PCP is assigned in `AUTO` mode, the system selects a provider through a deterministic load-balancing rule. The candidate set comprises every provider in the same practice as the member — those whose `practice_id` matches the member's `practice_id` — that is currently accepting new members (`accepting_new_members` is true) and whose `active_panel_count` is strictly below its effective cap, where the effective cap is the provider's `panel_capacity` when that is set and otherwise the practice's `panel_hard_cap`. Candidates are ranked first by `active_panel_count` in ascending order so that the most lightly loaded provider is preferred; ties on the lowest `active_panel_count` are broken by the earliest `created_at`, and any candidates sharing an identical `created_at` (common because creations read the same logical clock) are then ordered by the sequence in which they were persisted, never by `id`, giving a deterministic outcome. The first provider after ranking is selected. If the candidate set is empty, the assignment is rejected with `ERR_NO_PANEL_CAPACITY`.

Whether assignment is automatic or manual, a provider may only receive a member if it has room: the target or auto-selected provider's `active_panel_count` must be strictly below its effective cap. A request that would push a provider to or past its effective cap, or an `AUTO` request that finds no eligible provider, is rejected with `ERR_NO_PANEL_CAPACITY`.

### 3.5. Visit Slots and Booking

A provider publishes availability by creating a `VisitSlot`, supplying the `slot_type`, the interval bounds `starts_at` and `ends_at`, and an optional `virtual_capacity`. The `slot_type` is either `IN_PERSON` or `VIRTUAL`. An `IN_PERSON` slot is exclusive — it admits one visit per interval — whereas a `VIRTUAL` slot permits aggregate double-booking up to `virtual_capacity`. The `virtual_capacity` defaults to 1, must be at least 1 (a value below 1 is rejected with `ERR_VALIDATION`), and is ignored for `IN_PERSON` slots (which are treated as capacity 1). The `ends_at` must be strictly after `starts_at`; a slot whose `ends_at` is at or before `starts_at` is rejected with `ERR_VALIDATION`. A new slot's computed `booked_count` starts at zero and its `slot_state` starts at `OPEN`. The `booked_count` is the number of visits referencing the slot whose `clinical_status` is not `CANCELLED` and not `NO_SHOW`, recomputed on every booking and cancellation. The derived `slot_state` is `OPEN` while `booked_count` is below the slot's effective capacity and `FULL` once `booked_count` equals it.

A `Member` books a visit by supplying the `member_id`, the `slot_id`, the desired `visit_type`, and the `expected_slot_version` required for the concurrency guard in §2.6. The `visit_type` is one of `SAME_DAY` (urgent in-person care), `VIRTUAL` (telehealth), or `ANNUAL_PHYSICAL` (the yearly wellness exam). On a successful booking the system creates the `Visit` with `clinical_status` of `BOOKED` and `billing_status` of `NOT_BILLABLE`, copies the `provider_id` from the booking member's assigned PCP into the visit, increments the slot's `booked_count`, recomputes the slot's `slot_state`, and increments the slot's `version` by one.

Booking is subject to several business checks beyond the concurrency guard. The slot must not be exhausted: an `IN_PERSON` slot must have a `booked_count` of zero, and a `VIRTUAL` slot must have a `booked_count` strictly below its `virtual_capacity`; the slot's `starts_at` must precede its `ends_at`. A booking against an exhausted slot is rejected with `ERR_SLOT_UNAVAILABLE`. A member may not hold two visits in `BOOKED` or `CHECKED_IN` status whose slot intervals overlap, where intervals are treated as half-open from `starts_at` inclusive to `ends_at` exclusive; an overlapping booking is rejected with `ERR_MEMBER_DOUBLE_BOOKED`. When the requested `visit_type` is `ANNUAL_PHYSICAL`, the booking is permitted only when the member's `annual_physical_due_on` is null or is at or before the current clock instant — that is, the physical is due; booking an annual physical before it is due is rejected with `ERR_PHYSICAL_NOT_DUE`.

### 3.6. The Clinical Visit Lifecycle

A visit carries two independent status dimensions. The clinical dimension, `clinical_status`, moves through `BOOKED`, `CHECKED_IN`, `COMPLETED`, `CANCELLED`, and `NO_SHOW`, with `COMPLETED`, `CANCELLED`, and `NO_SHOW` terminal. The billing dimension, `billing_status`, evolves separately through `NOT_BILLABLE`, `BILLABLE`, `INVOICED`, and `WRITTEN_OFF`. The two dimensions advance independently of each other.

A `Provider` checks a member in, advancing the visit from `BOOKED` to `CHECKED_IN`, provided the visit is currently `BOOKED` and the owning member's `membership_status` is `ACTIVE` or `PAST_DUE`; a member who is `SUSPENDED` or `CANCELLED` cannot be seen, and a check-in attempt for such a member is rejected with `ERR_MEMBER_NOT_ELIGIBLE`. Check-in stamps the visit's `checked_in_at` with the current instant.

Completing a visit advances it from `CHECKED_IN` to `COMPLETED` and requires the visit to be `CHECKED_IN`. The provider submits the `service_lines` at completion — a list in which each entry names a `service_code`, a number of `units`, and a `unit_charge_cents` — and these are stored on the visit. If the submitted `service_lines` are non-empty, the visit's `billing_status` advances to `BILLABLE`; if they are empty, `billing_status` remains `NOT_BILLABLE`. Additionally, when the completed visit's `visit_type` is `ANNUAL_PHYSICAL`, the member's `annual_physical_due_on` is advanced to 365 days after the current clock instant, scheduling the next physical.

Two clinical exits remove a booking. A `Member` may cancel a visit that is still `BOOKED`, moving it to `CANCELLED`; cancellation decrements the slot's `booked_count` for the visit's `slot_id` and recomputes that slot's `slot_state`. A `Provider` may mark a still-`BOOKED` visit as `NO_SHOW`, but only once the clock has reached or passed the slot's `ends_at`; a no-show attempted while the clock is still before the slot's `ends_at` is rejected with `ERR_INVALID_STATE`. A successful no-show likewise decrements the slot's `booked_count` and recomputes `slot_state`. Any clinical transition requested from a state in which it is not defined — for instance checking in a visit that is not `BOOKED` — is rejected with `ERR_INVALID_STATE`.

On the billing dimension, a `Provider` issues an invoice for a visit whose `billing_status` is `BILLABLE` and whose `clinical_status` is `COMPLETED`, advancing `billing_status` to `INVOICED`; this creates an `Invoice` and computes its split per §3.7. Alternatively a `Provider` may write off a `BILLABLE` visit, advancing `billing_status` to `WRITTEN_OFF` with no invoice created. A billing transition requested from a state in which it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.7. Invoicing and the Insurance-vs-DPC Split

When a billable, completed visit is invoiced, the system creates an `Invoice` referencing the `member_id` and the originating `visit_id`, and computes the charge split from the visit's stored `service_lines`. Only the lines whose `service_code` is not in the practice's `dpc_covered_service_codes` contribute to what the member owes.

The gross charge, `gross_charge_cents`, is the sum over all service lines of that line's `units` multiplied by its `unit_charge_cents`. The DPC-covered portion, `dpc_covered_cents`, is the same sum restricted to lines whose `service_code` is in the practice's `dpc_covered_service_codes`; the member owes nothing on these. The non-DPC portion is the gross charge minus the DPC-covered portion.

The final split then takes one of two variants according to the member's `has_insurance` flag. When the member is not insured (the cash/DPC variant), `insurance_billed_cents` is zero and the member's `member_responsibility_cents` is the full non-DPC charge at full price. When the member is insured (the coinsurance variant), the non-DPC charge is routed to insurance — `insurance_billed_cents` equals the non-DPC portion — and the member owes only coinsurance on it: the non-DPC lines are first summed into the non-DPC total, then that single aggregate total is multiplied by the practice's `insurance_coinsurance_pct`, and that product is rounded half up exactly once to a whole number of cents to yield `member_responsibility_cents`. The rounding is applied once on the aggregated non-DPC total, never per line, so for the same `service_lines` the insured member's responsibility is strictly smaller than the uninsured member's. The `insurance_billed_cents` field is always present on the invoice; it carries the non-DPC portion for an insured member and is zero for an uninsured member.

### 3.8. Recurring Dues, the Member's Monthly Share, and Charges

The amount a member personally owes per billing cycle — their `member_share_cents` — is derived from the membership's plan, any employer sponsorship, and any late fee. The base fee is the membership's snapshot `monthly_fee_cents`. For an `ANNUAL_PREPAID` plan, the system first computes a discounted annual total by multiplying the base fee by twelve and then by one minus the practice's `annual_fee_discount_pct`, rounding that result half up to a whole number of cents; this discounted annual total is the period fee, charged once up front for the entire year. For a `MONTHLY` plan, the period fee is simply the base fee, charged every 30-day period. Sponsorship is then applied to the period fee: when the membership has a non-null `employer_seat_id`, the employer's covered amount is the period fee multiplied by the employer's `sponsorship_pct`, rounded half up to whole cents, and the member's share is the period fee minus that covered amount; when there is no sponsoring seat, the member's share equals the full period fee. The named rounding steps — the discounted annual total, then the employer's covered amount — are each applied half up in that order; for a sponsored annual plan the discount is applied (and rounded) before sponsorship is applied (and rounded). Finally, when the charge is the retry that takes a membership out of `PAST_DUE`, the practice's `late_fee_cents` is added on that next charge only. This share is recomputed at registration, at activation, at every billing-period rollover or reinstatement, and whenever an employer seat occupies the membership; releasing a seat (which occurs only as a cascade of cancellation or suspension) does not itself recompute the share.

Charging the membership fee is performed by a `Member` (on their own membership) or a `PlatformAdmin`. The caller supplies the `charge_kind`, the `amount_cents`, and a simulated processor `outcome`. For a membership-fee charge the `charge_kind` is `MEMBERSHIP_FEE` (a body whose `charge_kind` is anything else on this endpoint is rejected with `ERR_INVALID_REQUEST`); `amount_cents` must be at least zero (a negative `amount_cents` is rejected as a malformed request with `ERR_INVALID_REQUEST`); and `outcome` is either `SUCCEEDED` or `FAILED`. The charge creates a `Payment` recording the `member_id`, the `membership_id` (set for membership-fee charges and null for invoice charges), the `charge_kind`, the `amount_cents`, the `outcome`, and the computed `wallet_applied_cents`; the `invoice_id` is null for membership-fee charges. The `wallet_applied_cents` is computed first as the lesser of the member's `wallet_credit_cents` balance and the submitted `amount_cents`, and is recorded on the `Payment` regardless of `outcome`; the member's `wallet_credit_cents` balance is actually debited by `wallet_applied_cents` (never below zero) only when the charge succeeds. A `SUCCEEDED` membership-fee charge has a defined transition only when the membership is currently `PENDING_PAYMENT`, `PAST_DUE`, or `SUSPENDED`; a `SUCCEEDED` charge submitted against a membership in any other state (`ACTIVE`, or the terminal `CANCELLED`) has no defined transition and is rejected with `ERR_INVALID_STATE`, and this state check is applied before the amount-agreement and PCP-before-activation checks. The submitted `amount_cents` must equal the amount actually owed — the membership's `member_share_cents` (which includes the practice's `late_fee_cents` when the membership is currently `PAST_DUE`) — or the charge is rejected with `ERR_AMOUNT_MISMATCH`. When defined, a successful membership-fee charge then drives the `membership_status` transition appropriate to the current state as described in §3.3 and recomputes the assigned provider's panel counts where the lifecycle calls for it. A `FAILED` charge drives the `ACTIVE`-to-`PAST_DUE` transition only when the clock has reached or passed the membership's `current_period_end`; a `FAILED` charge in any other situation records the `Payment` but produces no state change or cascade.

Paying an invoice is performed by the owning `Member`. The caller supplies the `amount_cents` (which must be at least zero, a negative value rejected with `ERR_INVALID_REQUEST`) and the `outcome` (`SUCCEEDED` or `FAILED`); no `charge_kind` is supplied on this endpoint — the `charge_kind` for the resulting `Payment` is `INVOICE`, its `invoice_id` references the invoice being paid, and its `membership_id` is null. The invoice must be in `ISSUED` status to be paid. As with dues, the wallet credit to apply — the lesser of the member's `wallet_credit_cents` balance and the invoice's `member_responsibility_cents` — is computed first and recorded in `wallet_applied_cents` on the `Payment` regardless of `outcome`. The submitted `amount_cents` must equal the invoice's `member_responsibility_cents` net of the wallet credit applied, or the charge is rejected with `ERR_AMOUNT_MISMATCH`. On a successful charge the invoice advances from `ISSUED` to `PAID`, and the member's `wallet_credit_cents` is decremented by the `wallet_applied_cents`, never falling below zero; a `FAILED` charge records the `Payment` but leaves the invoice in `ISSUED` and the wallet balance unchanged. An invoice's `invoice_status` is one of `ISSUED` (the member owes), `PAID` (settled), or `VOID` (a terminal compensating reversal).

A `Provider` may void an `ISSUED` invoice, advancing its `invoice_status` to `VOID`; as a compensating cross-entity effect, the linked visit's `billing_status` is set to `WRITTEN_OFF`, so the visit is no longer treated as `INVOICED`. Voiding an invoice that is not `ISSUED` is rejected with `ERR_INVALID_STATE`.

### 3.9. Cancellation Proration

When a `Member` cancels from `ACTIVE`, the unused portion of the current billing period is refunded as wallet credit. The period length is 30 days for a `MONTHLY` plan and 365 days for an `ANNUAL_PREPAID` plan. The number of whole days elapsed is the time from the membership's `current_period_start` to the current clock instant, taken in whole days by flooring to the day. The remaining days are the period length minus the elapsed days, but never less than zero. Proration is computed on the member share actually paid this period — the membership's `member_share_cents` — not on the gross fee: the daily share is the `member_share_cents` divided by the period length in days, kept as an exact rational value, and the refund is that daily share multiplied by the remaining days, rounded half up to whole cents exactly once at the end. The resulting refund is added to the member's `wallet_credit_cents`. As boundary cases, a same-day cancellation (zero days elapsed) refunds the entire `member_share_cents` because the remaining days equal the full period length, while a cancellation made exactly at the period end (elapsed days equal to the period length) refunds nothing because the remaining days are zero. As noted in §3.3, cancelling from `PAST_DUE` or `SUSPENDED` yields no proration credit.

### 3.10. Care Plans

Following a completed annual physical, a `Provider` drafts a `CarePlan` by supplying the `member_id` and the `origin_visit_id` of the annual-physical visit that generated it, and an optional `goal_count` (defaulting to zero, never less than zero). A care plan is 1:1 with the member's active plan. Its `plan_status` is one of `DRAFT` (the provider is editing), `ACTIVE` (in effect), `UNDER_REVISION` (re-opened for edits), or `ARCHIVED` (superseded, terminal), and a new plan begins in `DRAFT` with `revision_number` zero. A provider may edit a plan's `goal_count` while it is in `DRAFT` or `UNDER_REVISION`.

Activating a plan moves it from `DRAFT` to `ACTIVE`. Activation requires the plan to be in `DRAFT`, its `goal_count` to be at least one, and the origin visit to be a completed annual physical — that is, the referenced visit's `clinical_status` is `COMPLETED` and its `visit_type` is `ANNUAL_PHYSICAL`. Attempting to activate a plan whose `goal_count` is below one is rejected with `ERR_CARE_PLAN_EMPTY`; attempting to activate when the origin visit is not a completed annual physical is rejected with `ERR_MEMBER_NOT_ELIGIBLE`. Activation produces no field cascade beyond the standard `updated_at` and `version` bump.

The plan supports a revision loop. A provider may reopen an `ACTIVE` plan, moving it to `UNDER_REVISION` and incrementing its `revision_number` by one. From `UNDER_REVISION` the plan may be activated again — back to `ACTIVE` — provided it is currently `UNDER_REVISION` and its `goal_count` is at least one (again with no field cascade beyond `updated_at` and `version`). A provider may also archive an `ACTIVE` plan, moving it to the terminal `ARCHIVED` state with no further cascade. Any of these transitions requested from a state in which it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.11. Specialist Referrals

A `Provider` requests a specialist referral arising from a visit by supplying the `member_id`, the `origin_visit_id` that prompted it, and the requested `specialty` (for example, cardiology). The new `Referral` begins in `REQUESTED` status. The `referral_status` is one of `REQUESTED` (awaiting authorization), `AUTHORIZED` (approved and sendable), `SENT` (dispatched to the specialist, terminal), `DENIED` (terminal), or `EXPIRED` (auto-expired, terminal).

A provider authorizes a `REQUESTED` referral, moving it to `AUTHORIZED`, only when the referral is currently `REQUESTED` and the owning member's `membership_status` is `ACTIVE` — only active members receive authorizations, and an attempt for a non-active owner is rejected with `ERR_MEMBER_NOT_ELIGIBLE`. Authorization stamps `authorized_at` with the current instant and sets `expires_at` to thirty days after authorization. A provider may instead deny a `REQUESTED` referral, moving it directly to the terminal `DENIED` state.

A provider sends an `AUTHORIZED` referral, moving it to the terminal `SENT` state, provided the referral is currently `AUTHORIZED` and the clock is still before its `expires_at`. Sending a referral at or after `expires_at` is rejected with `ERR_REFERRAL_EXPIRED`. An `AUTHORIZED` referral that is never sent is moved to the terminal `EXPIRED` state by the periodic sweep once the clock reaches or passes its `expires_at`. Any referral transition requested from a state in which it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.12. Messaging and After-Hours Escalation

A `Member` opens a message thread to their PCP by supplying the message `body`. The new `MessageThread` records the `member_id`, copies the `provider_id` of the member's assigned PCP at thread creation, and is created with `thread_status` of `OPEN`. The `thread_status` is one of `OPEN` (awaiting the provider), `ANSWERED` (the provider replied), `ESCALATED` (the response deadline was breached and the thread was routed to on-call), or `CLOSED` (terminal).

The thread's `priority` and `response_deadline` are computed at creation from the hour of day, in UTC, of its `created_at`. Business hours run from 08:00 inclusive to 18:00 exclusive UTC: when the creation hour is at least 8 and below 18 the priority is `ROUTINE`, otherwise — before 8 or at/after 18 — it is `AFTER_HOURS`. The 08:00 hour is `ROUTINE` and the 18:00 hour is `AFTER_HOURS`. A `ROUTINE` thread's `response_deadline` is its `created_at` plus 24 hours; an `AFTER_HOURS` thread's `response_deadline` is its `created_at` plus 4 hours, reflecting the faster after-hours service-level commitment.

A `Provider` replies to a thread, moving it to `ANSWERED`. A reply (also carrying a message `body`) is permitted on an `OPEN` thread only while the clock is still before the thread's `response_deadline`, and is permitted on an `ESCALATED` thread without that deadline restriction (since escalation has already routed it to on-call). When an `OPEN` thread's `response_deadline` has been reached or passed without a reply, the periodic sweep moves it from `OPEN` to `ESCALATED`. A `Member` closes an `ANSWERED` thread, moving it to the terminal `CLOSED` state. A thread transition requested from a state in which it is not defined is rejected with `ERR_INVALID_STATE`.

### 3.13. Administrative Time Control and the Periodic Sweep

A `PlatformAdmin` may advance the logical clock to a supplied instant, provided as `to_iso8601`; this becomes the time read by all deadline, expiry, grace-period, and billing-period rules thereafter. The administrator also triggers the periodic sweep, a single capability that performs three passes in one run: every `PAST_DUE` membership whose grace window has elapsed (the clock has reached or passed `past_due_since` plus the practice's `grace_period_days`) is moved to `SUSPENDED` with its full suspension cascade (panel recount and cancellation of that member's `BOOKED`/`CHECKED_IN` visits, each adjusting the affected slot's `booked_count` and `slot_state`); every `AUTHORIZED` referral whose `expires_at` the clock has reached or passed is moved to `EXPIRED`; and every `OPEN` message thread whose `response_deadline` the clock has reached or passed is moved to `ESCALATED`.

### 3.14. Validation Ordering

When several validations could apply to one request, they are evaluated in a fixed priority order so that the earliest applicable failure determines the error returned. Authentication is checked first: missing or unknown-role headers fail with `ERR_UNAUTHENTICATED`. Authorization is checked next: a role not permitted for the endpoint, or an entity-backed identity acting on a resource it does not own, fails with `ERR_FORBIDDEN`. Existence is then checked: every path or body identifier must resolve to an existing resource, validated left-to-right in the path, failing with `ERR_NOT_FOUND`. Request well-formedness follows: required body fields must be present and well-typed and enum values must lie within their declared domains, failing with `ERR_INVALID_REQUEST`. Value-range, positivity, and within-practice uniqueness constraints on well-typed fields — for example `panel_target`, `panel_hard_cap`, `monthly_fee_cents`, `annual_fee_discount_pct`, `insurance_coinsurance_pct`, `late_fee_cents`, `grace_period_days`, `panel_capacity`, `sponsored_seat_limit`, `sponsorship_pct`, `virtual_capacity`, `goal_count`, a provider's `npi`, and a member's `email` — are checked after well-formedness and after path/body existence, and each such violation fails with `ERR_VALIDATION`. State validity is checked next: the target must be in a state from which the requested transition is defined, failing with `ERR_INVALID_STATE`. The optimistic-concurrency check follows for the two version-guarded writes: a supplied `expected_slot_version` or `expected_employer_version` that does not match the live parent `version` fails with `ERR_STALE_VERSION`. Only after these structural checks do the domain-specific business rules apply — cross-entity eligibility (`ERR_MEMBER_NOT_ELIGIBLE`), slot availability (`ERR_SLOT_UNAVAILABLE`), member double-booking (`ERR_MEMBER_DOUBLE_BOOKED`), annual-physical timing (`ERR_PHYSICAL_NOT_DUE`), panel capacity (`ERR_NO_PANEL_CAPACITY`), seat limits (`ERR_SEAT_LIMIT_REACHED`), empty care plans (`ERR_CARE_PLAN_EMPTY`), expired referrals (`ERR_REFERRAL_EXPIRED`), charge-amount agreement (`ERR_AMOUNT_MISMATCH`), and PCP-before-activation (`ERR_PCP_REQUIRED`) — each evaluated within the workflow it guards as described above.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (for example, registering a practice, provider, employer, or member, allocating a seat, publishing a slot, booking a visit, drafting a care plan, requesting a referral, opening a message thread, issuing an invoice, or recording a charge payment) return `201 Created`. Operations that modify an existing resource, including state transitions and seat occupancy, return `200 OK`. The administrative clock and sweep endpoints also return `200 OK`. To reconstruct the full request body, response body, and side effects of any endpoint, refer to the Section 3 workflow that governs it.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/practices` | Create a practice (configuration root) | PlatformAdmin |
| GET | `/practices/{id}` | Fetch a practice | PlatformAdmin, Provider, Member, Employer |
| POST | `/providers` | Register a provider under a practice | PlatformAdmin |
| GET | `/providers/{id}` | Fetch a provider including computed panel fields | PlatformAdmin, Provider, Member |
| GET | `/providers` | List/filter providers by practice and acceptance | PlatformAdmin, Provider, Member |
| GET | `/providers/{id}/members` | List the members on a provider's panel | PlatformAdmin, Provider |
| GET | `/providers/{id}/visit-slots` | List a provider's visit slots | PlatformAdmin, Provider, Member |
| POST | `/employers` | Register an employer sponsor under a practice | PlatformAdmin |
| GET | `/employers/{id}` | Fetch an employer including occupied seat count | PlatformAdmin, Employer |
| GET | `/employers` | List/filter employers by practice | PlatformAdmin, Employer |
| POST | `/employers/{id}/seats` | Allocate a new open sponsored seat | PlatformAdmin, Employer |
| GET | `/employers/{id}/seats` | List an employer's seats | PlatformAdmin, Employer |
| GET | `/employer-seats/{id}` | Fetch a single sponsored seat | PlatformAdmin, Employer |
| GET | `/employer-seats` | List/filter sponsored seats by employer or member | PlatformAdmin, Employer |
| POST | `/employers/{id}/seats/{seatId}/occupy` | Occupy an open seat with a member (OCC-guarded) | PlatformAdmin, Employer |
| POST | `/members/register` | Self-register a member and its membership | Anonymous |
| GET | `/members/{id}` | Fetch a member | PlatformAdmin, Provider, Member |
| GET | `/members` | List/filter members by practice, provider, or status | PlatformAdmin, Provider |
| POST | `/members/{id}/assign-pcp` | Assign a PCP (AUTO or MANUAL) | PlatformAdmin |
| POST | `/members/{id}/cancel` | Cancel a membership | Member |
| GET | `/members/{id}/memberships` | List the member's membership record | PlatformAdmin, Provider, Member |
| GET | `/memberships/{id}` | Fetch a membership | PlatformAdmin, Member |
| GET | `/memberships` | List/filter memberships by member or seat | PlatformAdmin, Member, Employer |
| POST | `/memberships/{id}/charge` | Charge the membership fee | PlatformAdmin, Member |
| POST | `/providers/{id}/visit-slots` | Publish an availability slot | PlatformAdmin, Provider |
| GET | `/visit-slots/{id}` | Fetch a slot including booked count and state | PlatformAdmin, Provider, Member |
| POST | `/visits` | Book a visit into a slot (OCC-guarded) | Member |
| GET | `/visits/{id}` | Fetch a visit including both status dimensions | PlatformAdmin, Provider, Member |
| GET | `/visits` | List/filter visits by member, provider, or slot | PlatformAdmin, Provider, Member |
| POST | `/visits/{id}/check-in` | Check a member in | Provider |
| POST | `/visits/{id}/complete` | Complete a visit, recording service lines | Provider |
| POST | `/visits/{id}/cancel` | Cancel a booked visit | Member |
| POST | `/visits/{id}/no-show` | Mark a past-due booked visit as no-show | Provider |
| POST | `/visits/{id}/invoice` | Issue an invoice for a billable completed visit | Provider |
| POST | `/visits/{id}/write-off` | Write off a billable visit | Provider |
| POST | `/care-plans` | Draft a care plan from a completed annual physical | Provider |
| GET | `/care-plans/{id}` | Fetch a care plan | PlatformAdmin, Provider, Member |
| GET | `/care-plans` | List/filter care plans by member or origin visit | PlatformAdmin, Provider, Member |
| PATCH | `/care-plans/{id}` | Edit a draft/under-revision plan's goal count | Provider |
| POST | `/care-plans/{id}/activate` | Activate a plan | Provider |
| POST | `/care-plans/{id}/reopen` | Reopen an active plan for revision | Provider |
| POST | `/care-plans/{id}/archive` | Archive an active plan | Provider |
| POST | `/referrals` | Request a specialist referral from a visit | Provider |
| GET | `/referrals/{id}` | Fetch a referral | PlatformAdmin, Provider, Member |
| GET | `/referrals` | List/filter referrals by member or origin visit | PlatformAdmin, Provider, Member |
| POST | `/referrals/{id}/authorize` | Authorize a requested referral | Provider |
| POST | `/referrals/{id}/deny` | Deny a requested referral | Provider |
| POST | `/referrals/{id}/send` | Send an authorized, unexpired referral | Provider |
| POST | `/members/{id}/message-threads` | Open a message thread to the PCP | Member |
| GET | `/message-threads/{id}` | Fetch a message thread | PlatformAdmin, Provider, Member |
| GET | `/message-threads` | List/filter message threads by member or provider | PlatformAdmin, Provider, Member |
| GET | `/members/{id}/message-threads` | List a member's message threads | PlatformAdmin, Provider, Member |
| POST | `/message-threads/{id}/reply` | Reply to an open/escalated thread | Provider |
| POST | `/message-threads/{id}/close` | Close an answered thread | Member |
| GET | `/invoices/{id}` | Fetch an invoice with its split breakdown | PlatformAdmin, Provider, Member |
| GET | `/invoices` | List/filter invoices by member or visit | PlatformAdmin, Provider, Member |
| POST | `/invoices/{id}/charge` | Pay an issued invoice | Member |
| POST | `/invoices/{id}/void` | Void an issued invoice (compensating write-off) | Provider |
| GET | `/payments/{id}` | Fetch a payment | PlatformAdmin, Member |
| GET | `/payments` | List/filter payments by member, membership, or invoice | PlatformAdmin, Member |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/_billing/run_suspension_sweep` | Run the suspension, referral-expiry, and SLA sweep | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MEMBER_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_SLOT_UNAVAILABLE` | 409 Conflict |
| `ERR_MEMBER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_PHYSICAL_NOT_DUE` | 409 Conflict |
| `ERR_NO_PANEL_CAPACITY` | 409 Conflict |
| `ERR_SEAT_LIMIT_REACHED` | 409 Conflict |
| `ERR_CARE_PLAN_EMPTY` | 409 Conflict |
| `ERR_REFERRAL_EXPIRED` | 409 Conflict |
| `ERR_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PCP_REQUIRED` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |
