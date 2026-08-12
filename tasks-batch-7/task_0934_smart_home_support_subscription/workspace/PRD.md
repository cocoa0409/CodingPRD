# Smart-Home Support Subscription API — Product Requirements Document

## 1. Introduction

Households that fill their homes with connected hubs, cameras, sensors, thermostats and smart locks rarely buy a single product — they accumulate a fleet, and that fleet needs a support relationship rather than a warranty card. This document specifies the backend service behind such a relationship: a subscription-funded smart-home support programme that tracks every device a household owns from the moment it is claimed, answers trouble reports under a contractual response clock, escalates to a field technician when remote troubleshooting runs out of road, pushes firmware in controlled rings, sells and installs additional hardware, and routes broken units back to a depot, a manufacturer or an advance-replacement shipment depending on what the customer is entitled to.

The commercial core of the product is a promise measured in minutes. Every subscription tier buys a first-response target and an onsite-resolution target, and every minute that the support organisation fails to honour those targets is convertible into a service credit against the next invoice. Because the clock must be defensible to both the customer and the finance team, it is not a naive wall-clock difference: minutes spent waiting on the customer are banked separately from minutes spent outside the plan's coverage window, and the three buckets must always reconcile against the elapsed span. The same discipline governs money. Bundle discounts, install credits, proration, late-cancellation fees, no-show fees, overage charges and advance-replacement holds all land on one subscription ledger, and every percentage is pinned to a stated base with a stated rounding mode so that two implementations of this specification produce byte-identical cents.

Operationally, the system is a workflow orchestrator with several independent axes running in parallel over the same rows. A ticket simultaneously carries a workflow state, an SLA state and a dispatch state; a device simultaneously carries a lifecycle state and a firmware state. These axes advance on different triggers and must not be collapsed into one another. Layered on top are four ordered account gates that pre-empt ordinary state errors, an optimistic-concurrency discipline on three write paths where a second write is legitimate product behaviour, and five conservation invariants that any compensating pair of operations must leave undisturbed. The remainder of this document specifies the whole of that behaviour: §2 fixes the global contract, §3 narrates the business workflows, §4 lists every endpoint and §5 catalogues every error code.

---

## 2. Global Specifications & System-Wide Principles

Every path in this specification is mounted under the API prefix `/smart-home-support`.

### 2.1. User and Role-Based Access Control

Authentication is header-based. Every request must carry two headers: `X-User-Role`, naming the role the caller is acting as, and `X-User-ID`, identifying the caller. Exactly six roles exist and their spellings are fixed: `Owner`, `Member`, `BillingAdmin`, `SupportAgent`, `Technician` and `PlatformAdmin`. A request whose `X-User-Role` header is missing or blank, or whose value is not one of those six literal strings, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The same rejection applies when `X-User-ID` is missing or blank while `X-User-Role` names one of the entity-backed roles — `Owner`, `Member`, `BillingAdmin` or `Technician`.

Three of the roles are household-backed. When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `HouseholdMember` row, and that row must be active (`is_active` true) with a `member_role` of `OWNER`. When `X-User-Role` is `Member`, `X-User-ID` is likewise the `id` of a `HouseholdMember` row, active, whose `member_role` is `MEMBER`. When `X-User-Role` is `BillingAdmin`, `X-User-ID` is the `id` of an active `HouseholdMember` row whose `member_role` is `BILLING_ADMIN`. In all three cases the member's `household_id` is the caller's row scope: ownership checks on any resource that references a household compare that resource's household to `X-User-ID`'s `household_id`. A header identity that resolves to no member row, to a deactivated member row, or to a member row whose `member_role` does not match the header role is rejected with `ERR_MEMBER_NOT_FOUND` (HTTP 404).

`Technician` is the fourth entity-backed role: when `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician` row, and ownership checks compare the `technician_id` recorded on the slot behind the targeted visit or slot to `X-User-ID`. A header identity that resolves to no technician row is likewise `ERR_MEMBER_NOT_FOUND`.

The remaining two roles are operator roles with no persisted identity. When `X-User-Role` is `SupportAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `agent_user_id` on every `RemoteSession` the agent opens, but never compares it to any entity's `id`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier, never compared to any entity's `id`. Both operator roles act across all households.

Role authority is per-endpoint and is listed in the table in §4. A syntactically valid role that is not listed for the endpoint it addresses is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). A listed entity-backed role that addresses a row outside its scope — an `Owner` touching another household's device, a `Technician` completing a visit booked into another technician's slot — is rejected with `ERR_ROW_SCOPE_DENIED` (HTTP 403). Concretely, row scope for `Owner`, `Member` and `BillingAdmin` compares the acting member's `household_id` against the household owning the target row: `Device.household_id` for a device, `Ticket.household_id` for a ticket, `Subscription.household_id` for a subscription, `AddOnOrder.household_id` for an order, the household behind the device for an RMA case or a firmware rollout, and the household behind the ticket for a visit. Row scope for `Technician` compares the acting technician's `id` against the `technician_id` of the slot behind the target visit, the target slot, or the rollout whose result is being reported.

Broadly, an `Owner` holds full household-scoped authority over devices, tickets, transfers, firmware deferral and cancellation; a `Member` may raise and answer tickets and read household rows but owns no device, billing or transfer authority; a `BillingAdmin` owns tier changes, the overage policy and add-on purchasing but may not touch devices or tickets; a `SupportAgent` owns the ticket and RMA surfaces across all households; a `Technician` owns availability slots, onsite visit outcomes and firmware result reporting; and a `PlatformAdmin` owns configuration, the billing cycle and the logical clock.

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

Every list endpoint accepts two optional query parameters. `limit` controls page size: it defaults to 10 when omitted, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` controls the starting position: it defaults to 0 when omitted and its minimum accepted value is 0. A `limit` below 1 or above 100, or an `offset` below 0, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

List results are always sorted by `created_at` in ascending order. The `meta` block of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` is true exactly when rows remain beyond the current page.

### 2.4. Resource Identity, Timestamps and the Version Ledger

Every persisted row carries an `id` that is a server-minted UUID string with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most rows additionally carry an `updated_at` timestamp in the same format, refreshed on every mutation of that row, and a `version` integer that begins at 1 when the row is created and increases by exactly 1 each time the row is mutated.

Two entities are configuration entities and are the exception: a `SubscriptionPlan` row and a `DeviceCatalogEntry` row carry only `id` and `created_at`. Neither `updated_at` nor `version` exists on those two entities, and neither is returned in their payloads.

The version ledger is normative because three endpoints use `version` for optimistic concurrency (§2.7). The governing rule for every entity is this: **a single request bumps a given row's `version` by at most 1, no matter how many fields of that row the request touches and no matter how many state-machine hops that row traverses inside the request.** An RMA case that walks `AWAITING_RETURN → RETURN_WINDOW_EXPIRED → CHARGED → CLOSED` inside one call ends the call with its `version` one higher than it started, not three higher. Per entity:

- **`Household`** — bumped by a change of `account_status`, and by the two billing-cycle cascade hops that suspend or reinstate the account. Recomputation of the derived counters `entitled_device_count` and `active_device_count` does not by itself bump `Household.version`.
- **`HouseholdMember`** — bumped when the member row itself is mutated.
- **`Subscription`** — bumped by a tier change, by an overage-policy change, by a cancellation request, by a billing-cycle close, by the placement of an add-on order, and by the advance-replacement hold charge described in §3.11. Booking an overage charge, a visit fee or a service credit onto the subscription's ledgers does not by itself bump `Subscription.version`.
- **`Device`** — bumped by every operation that changes either of its two status axes or its onboarding fields: activation (successful or failed), reclaim, decommission, transfer, transfer acceptance, entry into and exit from service hold, entry into and exit from RMA suspension, enrolment in a firmware ring, every rollout result, deferral, retry, and blocking or unblocking of a rollout. It is also bumped by the opening of an RMA case against the device.
- **`Ticket`** — bumped by every operation that advances any of its three axes, once per request even when two or three axes move together.
- **`RemoteSession`**, **`VisitSlot`**, **`Visit`**, **`FirmwareCampaign`**, **`FirmwareRollout`**, **`AddOnOrder`**, **`RmaCase`**, **`SatisfactionSurvey`**, **`ServiceCredit`** — bumped when the row itself is mutated by the operations described in §3.

Read-only endpoints never bump a version and never refresh `updated_at`. In particular the SLA projection endpoint described in §3.6 recomputes the clock partition for the response only and writes nothing.

### 2.5. The Logical Clock

The service keeps a **logical clock** rather than reading the host's wall clock. Before any client sets it, the clock reads exactly `2026-05-01T00:00:00Z`, and it never falls back to real time. Every deadline, expiry, window, cutoff and elapsed-minute computation in this document is evaluated against this clock, including activation-token expiry, the SLA clock partition, the visit cutoff, the reopen window, the survey window, the RMA return deadline, the firmware deferral ceiling and the billing cycle boundary.

An administrative capability sets the clock to a supplied instant, taking a single field `to_iso8601` and answering with the field `current_utc` carrying the clock's new value. Setting the clock performs no state transitions of its own: no ticket breaches, no window closes and no campaign halts merely because time moved. Those consequences are realised only when a subsequent request evaluates the rule in question.

### 2.6. Money, Counting and Rounding Conventions

All monetary amounts in this system are integers denominated in **cents**; there are no fractional currency values anywhere in a request or a response. Wherever a computation produces a non-integer amount, the result is rounded **half up** to a whole number of cents — a value whose fractional part is exactly one half rounds away from zero, to the larger magnitude. Three computations depart from half-up rounding and say so explicitly at the point of use: the per-cycle credit cap uses **floor**, the ring failure rate is rounded half up to **four decimal places** before its threshold comparison, and every minute count and day count in this document is obtained by **floor** division (a partial minute or a partial day never counts).

Two rounding-order rules are normative because they change the answer. First, in add-on order proration each **line** is rounded to whole cents and only then are the rounded line values summed; summing the unrounded line values and rounding once at the end is a different and incorrect number. Second, in add-on bundle pricing the discount is computed from the subtotal alone and rounded once, before any install charge or proration is added to the order.

Counts of devices, credits, slots, minutes and attempts are integers. Where a formula could otherwise produce a negative count — remaining install credits, remaining cap room, remaining warranty days, remaining cycle days — the result is clamped at zero.

### 2.7. Optimistic Concurrency on Parent Rows

Three write paths carry an optimistic-concurrency guard, and only those three. In each case the guarded write is a request whose repetition is legitimate product behaviour — a second RMA case genuinely supersedes the first, a second tier change genuinely supersedes a pending downgrade, a second add-on order is genuinely a second purchase — so the only way the service can reject a caller who is acting on an out-of-date view is to compare a version the caller supplies against the parent row's current `version`.

- **Opening an RMA case** requires the non-optional field `expected_device_version`, carrying the client's last observed `version` of the `Device` named by `device_id`. If it does not equal that device's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written.
- **Changing a subscription's tier** requires the non-optional field `expected_subscription_version`, carrying the client's last observed `version` of the target `Subscription`. A mismatch with that subscription's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Placing an add-on order** requires the non-optional field `expected_subscription_version`, carrying the client's last observed `version` of the `Subscription` named by `subscription_id`. A caller who priced a basket against an install-credit balance that has since been consumed will find its supplied version no longer matching, and the order is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field, and no other endpoint may reject a request for staleness.

### 2.8. The Four Ordered Account Gates

Four **write gates** sit between authorisation and business logic. They are evaluated top to bottom after authentication, authorisation, row scope, request-shape validation and optimistic concurrency have all passed, and **before** any state-machine from-state check or any business rule. The first gate whose condition holds wins: lower gates and every downstream state error are never reported for that request.

1. **Account suspended.** If the `Household` that scopes the target row has `account_status` equal to `SUSPENDED`, the request is refused with `ERR_ACCOUNT_SUSPENDED` (HTTP 403). This gate guards every mutating endpoint except household registration, the account-status endpoint itself and the clock-setting capability — the account-status exemption is what makes a suspended account reinstatable.
2. **Device decommissioned.** If the `Device` the request resolves to has `lifecycle_status` equal to `DECOMMISSIONED`, the request is refused with `ERR_DEVICE_DECOMMISSIONED` (HTTP 409). This gate guards every mutating endpoint whose target row resolves to a device: the device actions themselves, ticket creation that names a `device_id`, RMA opening, and the rollout actions.
3. **Ticket closed.** If the `Ticket` the request resolves to has `workflow_status` equal to `CLOSED`, the request is refused with `ERR_TICKET_CLOSED` (HTTP 409). This gate guards every mutating endpoint whose target row resolves to a ticket, with one exemption: survey submission, so that a closed ticket can still be rated.
4. **Subscription cancelled.** If the household's `Subscription` has `status` equal to `CANCELLED`, the request is refused with `ERR_SUBSCRIPTION_CANCELLED` (HTTP 409). This gate guards every mutating endpoint whose target row resolves to a household, except the account-status endpoint and the creation of a subscription.

Because the gates are ordered, a household that is both suspended and cancelled reports `ERR_ACCOUNT_SUSPENDED`, not `ERR_SUBSCRIPTION_CANCELLED`; and a decommissioned device belonging to a suspended household reports `ERR_ACCOUNT_SUSPENDED`, not `ERR_DEVICE_DECOMMISSIONED`.

### 2.9. The Validation Ladder

Validation is a single ordered ladder of 51 rungs. Rungs are evaluated strictly in ascending priority order; **the first rung that fails is the error reported, and no later rung is evaluated**. The ladder is stated once here in full and its individual conditions are restated in business context throughout §3.

1. `X-User-Role` is present and non-blank, and `X-User-ID` is present and non-blank whenever `X-User-Role` is one of the entity-backed roles `Owner`, `Member`, `BillingAdmin` or `Technician` — otherwise `ERR_UNAUTHENTICATED`. Applies to every endpoint.
2. `X-User-Role` is exactly one of `Owner`, `Member`, `BillingAdmin`, `SupportAgent`, `Technician`, `PlatformAdmin` — otherwise `ERR_UNAUTHENTICATED`. Applies to every endpoint.
3. The role is listed among the target endpoint's authorised roles — otherwise `ERR_FORBIDDEN_ROLE`. Applies to every endpoint.
4. For an entity-backed household role, `X-User-ID` resolves to a `HouseholdMember` row with `is_active` true whose `member_role` matches the header role; for `Technician`, `X-User-ID` resolves to a `Technician` row — otherwise `ERR_MEMBER_NOT_FOUND`. Applies to every endpoint whose authorised roles include `Owner`, `Member`, `BillingAdmin` or `Technician`.
5. Every `Household` id named in the path or body exists — otherwise `ERR_HOUSEHOLD_NOT_FOUND`. Applies to every endpoint taking a `household_id`.
6. Every `SubscriptionPlan` id named in the path or body exists, covering both `plan_id` and `target_plan_id` — otherwise `ERR_PLAN_NOT_FOUND`. Applies to subscription creation, tier change and the single-plan read.
7. Every `Subscription` id named in the path or body exists — otherwise `ERR_SUBSCRIPTION_NOT_FOUND`. Applies to the subscription endpoints and to add-on order placement. The same error is reported when an operation needs the household's in-force subscription and the household has none.
8. Every `DeviceCatalogEntry` id named in the path or body exists, including every `catalog_entry_id` appearing inside an order's `lines` — otherwise `ERR_CATALOG_ENTRY_NOT_FOUND`. Applies to device claiming, add-on order placement, campaign creation and the single-catalog read.
9. Every `Device` id named in the path or body exists, including every entry of a ring launch's `device_ids` list — otherwise `ERR_DEVICE_NOT_FOUND`. Applies to the device endpoints, ticket creation, RMA opening and ring launching.
10. Every `Ticket` id named in the path or body exists — otherwise `ERR_TICKET_NOT_FOUND`. Applies to the ticket endpoints, visit booking and RMA opening.
11. Every `RemoteSession` id named in the path exists — otherwise `ERR_SESSION_NOT_FOUND`. Applies to session completion and the single-session read.
12. Every `Technician` id named in the path exists — otherwise `ERR_TECHNICIAN_NOT_FOUND`. Applies to slot publication and the single-technician read.
13. Every `VisitSlot` id named in the path or body exists — otherwise `ERR_SLOT_NOT_FOUND`. Applies to visit booking, rescheduling and the single-slot read.
14. Every `Visit` id named in the path exists — otherwise `ERR_VISIT_NOT_FOUND`. Applies to the visit action endpoints and the single-visit read.
15. Every `FirmwareCampaign` id named in the path exists — otherwise `ERR_CAMPAIGN_NOT_FOUND`. Applies to the campaign endpoints.
16. Every `FirmwareRollout` id named in the path exists — otherwise `ERR_ROLLOUT_NOT_FOUND`. Applies to the rollout endpoints.
17. Every `AddOnOrder` id named in the path exists — otherwise `ERR_ORDER_NOT_FOUND`. Applies to order fulfilment and the single-order read.
18. Every `RmaCase` id named in the path exists — otherwise `ERR_RMA_NOT_FOUND`. Applies to the RMA action endpoints and the single-case read.
19. Row scope, as defined in §2.1 — otherwise `ERR_ROW_SCOPE_DENIED`. Applies to every endpoint whose authorised roles include an entity-backed role and whose target row is household-scoped or technician-scoped.
20. Request-body shape: every required field is present, every field has the correct JSON type, and every declared numeric range is honoured — a survey `score` between 1 and 5 inclusive, a line `quantity` of at least 1, a `limit` between 1 and 100, an `offset` of at least 0, between 1 and 5 entries in `lines`, an `end_at` strictly after its `start_at`, and a `region_code` of exactly three uppercase letters. Otherwise `ERR_INVALID_REQUEST`. Applies to every endpoint.
21. Enum membership. This rung fires for exactly these fields and no others: `SubscriptionPlan.tier`, `SubscriptionPlan.coverage_mode`, `HouseholdMember.member_role`, the `account_status` request field, `DeviceCatalogEntry.device_class`, the elements of a technician's `skills` array, `Ticket.severity`, the `outcome` supplied when completing a remote session, `FirmwareCampaign.kind`, the `result` supplied when reporting a rollout, the `payment_outcome` supplied when closing a cycle, and the list filters `lifecycle_status`, `workflow_status` and the slot `status` filter. A value outside the field's enumeration is rejected with `ERR_INVALID_ENUM` (HTTP 422). No other field routes here; every other bad value is `ERR_INVALID_REQUEST`.
22. Optimistic concurrency: the supplied `expected_device_version` or `expected_subscription_version` equals the current `version` of the named parent row — otherwise `ERR_STALE_VERSION`. Applies to RMA opening, tier change and add-on order placement.
23. Gate 1 — the household scoping the target row is `SUSPENDED`, giving `ERR_ACCOUNT_SUSPENDED`. Applies to every mutating endpoint except household registration, the account-status endpoint and the clock capability.
24. Gate 2 — the resolved device is `DECOMMISSIONED`, giving `ERR_DEVICE_DECOMMISSIONED`. Applies to every mutating endpoint whose target row resolves to a device.
25. Gate 3 — the resolved ticket is `CLOSED`, giving `ERR_TICKET_CLOSED`. Applies to every mutating endpoint whose target row resolves to a ticket, except survey submission.
26. Gate 4 — the household's subscription is `CANCELLED`, giving `ERR_SUBSCRIPTION_CANCELLED`. Applies to every mutating household-scoped endpoint except the account-status endpoint and subscription creation.
27. The target row's current state on the relevant axis permits the requested transition, together with any other state precondition of that transition for which no more specific rung exists — otherwise `ERR_INVALID_STATE`. Applies to every state-changing endpoint, with one exemption: visit booking does **not** report this error for a ticket that is simply not dispatch-ready. The dispatch-readiness of a ticket is reported by rung 40 instead, so that rung remains reachable for tickets still in `NEW`, `TRIAGED` or `REMOTE_DIAG`.
28. The claimed `serial_number` starts with the catalog entry's `serial_prefix` — otherwise `ERR_SERIAL_MODEL_MISMATCH` (HTTP 422). Applies to device claiming only.
29. The claimed `serial_number` is not already recorded on any `Device` row, in any `lifecycle_status` including `DECOMMISSIONED` — otherwise `ERR_SERIAL_ALREADY_CLAIMED`. Applies to device claiming only.
30. The logical clock is strictly before the device's `activation_expires_at` — otherwise `ERR_ACTIVATION_TOKEN_EXPIRED`. Applies to device activation.
31. The device's `activation_attempts` is strictly below 3 before this attempt, and after a mismatching code the post-increment value is still strictly below 3 — otherwise `ERR_ACTIVATION_ATTEMPTS_EXCEEDED`. Applies to device activation.
32. The supplied `activation_code` equals the device's `activation_token` — otherwise `ERR_ACTIVATION_CODE_INVALID` (HTTP 422). Because this rung sits below rungs 30 and 31, an expired token reports expiry rather than a bad code, and a third bad code reports the attempt cap rather than a bad code. Applies to device activation.
33. The device's `lifecycle_status` is `RECLAIMABLE` — otherwise `ERR_RECLAIM_NOT_ELIGIBLE`. Applies to device reclaim.
34. No `RmaCase` for the device has a `status` of `OPEN`, `ROUTED`, `ADVANCE_SHIPPED` or `AWAITING_RETURN` — otherwise `ERR_RMA_IN_FLIGHT`. Applies to three operations: ring launching (for campaigns of either kind), device transfer and device decommission.
35. For a campaign whose `kind` is `FEATURE_OPTIONAL` only, no `Ticket` referencing the device has a `workflow_status` other than `RESOLVED` or `CLOSED` — otherwise `ERR_OPEN_TICKET_BLOCKS_ROLLOUT`. A campaign whose `kind` is `SECURITY_MANDATORY` skips this rung entirely. Applies to ring launching.
36. The requested ring window does not overlap, on a closed-interval basis, an existing `PENDING` rollout window for the same device — otherwise `ERR_ROLLOUT_WINDOW_OVERLAP`. Applies to ring launching.
37. The owning campaign's `status` is not `HALTED` — otherwise `ERR_CAMPAIGN_HALTED`. Applies to rollout retry only. Only retry can reach this rung: a halt blocks every `PENDING` rollout of the ring inside the same request, so result reporting and deferral always fail the earlier from-state rung instead, while a `ROLLED_BACK` rollout survives the halt and is legally retryable on its own axis.
38. The owning campaign's `kind` is `FEATURE_OPTIONAL` and the supplied `defer_until` is at or before the logical clock plus 14 days — otherwise `ERR_DEFER_NOT_ALLOWED`. Applies to rollout deferral.
39. The rollout's `retry_count` is strictly below 2 — otherwise `ERR_RETRY_CAP_EXCEEDED`. Applies to rollout retry.
40. The ticket's `dispatch_status` is `REQUIRED`, `RESCHEDULING` or `NO_SHOW` — otherwise `ERR_DISPATCH_NOT_REQUIRED`. A visit may not be booked for a ticket that never escalated, and this rung, not rung 27, is what a ticket still in `NEW`, `TRIAGED` or `REMOTE_DIAG` reports. Applies to visit booking.
41. The chosen slot's `region_code` equals the ticket household's `region_code` — otherwise `ERR_SLOT_REGION_MISMATCH` (HTTP 422). Applies to visit booking and visit rescheduling.
42. The chosen slot's `status` is `OPEN` — otherwise `ERR_SLOT_UNAVAILABLE`. Applies to visit booking and visit rescheduling.
43. The chosen slot does not buffer-overlap any `BOOKED` slot of the same technician, per the travel-buffer rule of §3.8 — otherwise `ERR_SLOT_BUFFER_CONFLICT`. Applies to visit booking and visit rescheduling.
44. The logical clock is at or after the visit's `scheduled_start_at` — otherwise `ERR_VISIT_NOT_STARTED`. Applies to visit completion and no-show reporting.
45. The logical clock is strictly before the ticket's `resolved_at` plus 168 hours — otherwise `ERR_REOPEN_WINDOW_CLOSED`. Applies to ticket reopening.
46. No `SatisfactionSurvey` row already exists for the ticket — otherwise `ERR_SURVEY_ALREADY_SUBMITTED`. Applies to survey submission.
47. The ticket's `survey_solicited_at` is not null and the logical clock is strictly before `survey_solicited_at` plus 72 hours — otherwise `ERR_SURVEY_WINDOW_CLOSED`. Applies to survey submission.
48. The case's `routing_target` is `ADVANCE_REPLACEMENT` — otherwise `ERR_ADVANCE_REPLACEMENT_NOT_ELIGIBLE`. Applies to advance-replacement shipping.
49. When the case's `status` is `AWAITING_RETURN`, the logical clock is strictly after the case's `return_deadline_at` — otherwise `ERR_RETURN_WINDOW_OPEN`. Applies to closing the return window.
50. The post-operation `entitled_device_count` does not exceed the plan's `included_device_count` unless the subscription's `allow_overage` is true — otherwise `ERR_DEVICE_CAP_EXCEEDED`. Applies to device claiming, transfer acceptance and add-on order placement.
51. Remaining credit-cap room for the current cycle is greater than zero when an explicit SLA evaluation would otherwise issue a credit — otherwise `ERR_CREDIT_CAP_REACHED`. Applies to explicit SLA evaluation only; the first-response settlement described in §3.6 never reports this error and simply issues no credit when no room remains.

### 2.10. Conservation Invariants

Five quantities are conserved. Every compensating pair of operations must leave them intact, and an implementation that satisfies the individual rules of §3 but violates one of these has a defect.

- **Ticket minutes.** For any evaluation instant, `sla_counted_minutes` plus `sla_paused_minutes` plus `sla_uncovered_minutes` equals the whole minutes elapsed from the ticket's `created_at` to that instant, obtained by floor division. Parking a ticket on the customer and then receiving the customer's reply moves minutes from the counted bucket to the paused bucket; it must never create or destroy minutes.
- **Entitled devices.** Summing `entitled_device_count` over all households equals the number of `Device` rows whose `lifecycle_status` is `CLAIMED`, `ACTIVE`, `SERVICE_HOLD`, `SUSPENDED_RMA` or `TRANSFER_PENDING`. Offering a device and then accepting the transfer moves one unit from the source household's count to the target's; the global total is unchanged. Decommissioning is the only operation permitted to lower the global total, and it lowers it by exactly one.
- **Technician slots.** For every technician, `open_slot_count` plus `booked_slot_count` plus `blocked_slot_count` equals `total_slot_count`. Booking moves a slot from open to booked; an early cancellation moves it back; a late cancellation or a no-show moves it to blocked. No path may leave a slot uncounted.
- **Service-credit cents.** For every subscription, `credits_issued_cents_this_cycle` equals the sum of `amount_cents` over the `ServiceCredit` rows whose `subscription_id` is that subscription and whose `cycle_index` equals the subscription's current `cycle_index`, and that sum never exceeds the floor of half the subscription's `monthly_fee_cents`. Every issued cent is represented by exactly one `ServiceCredit` row.
- **Install credits.** For every subscription, `install_credits_remaining` plus `install_credits_consumed` equals `install_credits_granted`. Credits are never destroyed: a cycle close grants and an add-on order consumes, and the two always reconcile against the cumulative grant.

### 2.11. Path Resolution and Nested Reads

Path parameters are validated left to right. A request that names a parent resource and a child resource resolves the parent first; if the parent does not exist the parent's not-found error is reported and the child is never looked up. The existence rungs of §2.9 encode this ordering, which is why, for example, a slot publication addressed to a non-existent technician reports `ERR_TECHNICIAN_NOT_FOUND` rather than a body-shape error.

All list endpoints accept the filters named in §3 and in the table of §4. A filter naming a value outside a closed enumeration is subject to rung 21 when the filter is one of `lifecycle_status`, `workflow_status` or the slot `status`; every other filter with a malformed value is subject to rung 20.

---

## 3. Business Logic & Workflows

### 3.1. Households, Members and Account Standing

A household is the unit of account. Registering one is a platform-operator act: the operator supplies a `name` of between 1 and 120 characters, a `region_code` and a `billing_email`, and the service creates the row with `account_status` `ACTIVE`, `entitled_device_count` 0 and `active_device_count` 0. The `region_code` is a dispatch key rather than a postal code — it must be exactly three uppercase letters, so `NWA` is acceptable and `NW1` is not, and a visit may only be booked into a slot whose own region matches it.

Two derived counters hang off every household and are recomputed whenever the underlying device population changes. `entitled_device_count` counts the household's devices whose `lifecycle_status` is `CLAIMED`, `ACTIVE`, `SERVICE_HOLD`, `SUSPENDED_RMA` or `TRANSFER_PENDING`; this is the count the tier entitlement cap is measured against. `active_device_count` is the narrower count of devices whose `lifecycle_status` is `ACTIVE`, `SERVICE_HOLD` or `SUSPENDED_RMA`. Devices in `RECLAIMABLE` or `DECOMMISSIONED` are excluded from both.

People are added to a household one at a time, each carrying a `full_name`, an `email` and a `member_role` of `OWNER`, `MEMBER` or `BILLING_ADMIN`. A newly added member is created with `is_active` true; once that flag is false the member row fails the row-scope checks of §2.1 and any request authenticating as that member is refused with `ERR_MEMBER_NOT_FOUND`. The `member_role` recorded on the row must equal the role named in the `X-User-Role` header when that member authenticates — a member whose stored role is `MEMBER` cannot act as `Owner` merely by changing the header.

Account standing moves on an axis of its own. A platform operator may drive `account_status` from `ACTIVE` to `SUSPENDED`, which stamps `suspended_at` with the logical-clock instant and, from that moment, arms gate 1 for every subsequent mutating request scoped to the household. The reverse move, `SUSPENDED` back to `ACTIVE`, clears `suspended_at` to null and disarms the gate — the account axis is therefore cyclic, and reinstatement is possible precisely because the account-status endpoint is itself exempt from gates 1 and 4. The third move, `ACTIVE` to `CLOSED`, is terminal and carries a second precondition beyond the from-state: the household's subscription must already be `CANCELLED`. All three moves bump `Household.version` by exactly one. Requesting a move that the current status does not permit — for instance suspending an already-suspended account — is refused with `ERR_INVALID_STATE`, and an `account_status` value outside the three-member enumeration is refused with `ERR_INVALID_ENUM`.

Household reads are broad. A single household read returns the row including both derived counters and is available to `PlatformAdmin`, `SupportAgent`, `Owner`, `Member` and `BillingAdmin`. Members are listed with an optional `household_id` filter alongside `limit` and `offset`, and any single member row may be read by id.

### 3.2. Plans, Subscriptions, Tier Changes and the Billing Cycle

A **subscription plan** is pure configuration and carries no `version` and no `updated_at`. Each plan fixes a `tier` of `BASIC`, `PLUS` or `PRO`; a `monthly_fee_cents` of at least 0, which is the base for every SLA and CSAT credit percentage in the system; an `included_device_count` of at least 1; an `overage_fee_cents_per_device` of at least 0 charged monthly for each device beyond the included count; and a `coverage_mode` of either `BUSINESS_HOURS` or `TWENTY_FOUR_SEVEN`, which decides which wall-clock minutes count toward the SLA. Six integers of at least 1 each carry the service promise: `first_response_minutes_p1`, `first_response_minutes_p2` and `first_response_minutes_p3` state the first-response target in counted minutes per severity, and `onsite_resolution_hours_p1`, `onsite_resolution_hours_p2` and `onsite_resolution_hours_p3` state the onsite-resolution target in counted hours per severity. Three more fields round out the plan: `warranty_extension_months`, a count of at least 0 added to a device's base warranty term while this plan is the household's active plan at claim time; `included_install_credits`, a count of at least 0 granted at subscription creation and re-granted at every cycle close; and the boolean `advance_replacement_eligible`, which decides whether households on this plan may be routed to an advance replacement on an RMA.

Starting a subscription binds a household to a plan. The operator supplies `household_id`, `plan_id` and optionally `allow_overage` (which defaults to false). The service pins `monthly_fee_cents` by copying it from the plan, sets `cycle_index` to 1, sets `cycle_start_at` to the current logical-clock instant, computes `cycle_end_at` as `cycle_start_at` plus 30 days, and grants the plan's `included_install_credits` — setting both `install_credits_granted` and `install_credits_remaining` to that number while `install_credits_consumed` stays 0. The new row begins in `ACTIVE`, and exactly one non-`CANCELLED` subscription may exist per household. Subscription creation is exempt from gate 4, so a household whose previous subscription was cancelled can be re-subscribed.

The subscription row is also the household's running ledger. `overage_device_count` counts the household's devices flagged `is_overage` whose `lifecycle_status` is `CLAIMED`, `ACTIVE`, `SERVICE_HOLD`, `SUSPENDED_RMA` or `TRANSFER_PENDING`. `overage_charges_cents_this_cycle` accumulates the overage charges booked in the current cycle. `credits_issued_cents_this_cycle` accumulates the service credits issued in the current cycle. `next_invoice_credit_cents` carries the credits accrued in the current cycle that will be applied to the next invoice, and `next_invoice_adjustment_cents` carries the chargeable side: overage charges, add-on order totals, late-cancellation and no-show fees, and charged advance-replacement holds. `install_credits_remaining` is always `install_credits_granted` minus `install_credits_consumed` and is never negative.

**Changing tier** is guarded by optimistic concurrency (§2.7): the caller supplies `target_plan_id` and `expected_subscription_version`. The direction of the change is decided by comparing the target plan's `monthly_fee_cents` against the subscription's currently pinned `monthly_fee_cents`, and the two directions behave completely differently. When the target fee is **strictly greater** than the current fee the change is an immediate upgrade: `plan_id` is switched to the target plan, `monthly_fee_cents` is re-pinned from the target plan, any recorded `pending_tier_plan_id` is cleared to null, and a prorated charge is booked. That charge is the difference between the new fee and the old fee, multiplied by the number of whole days remaining in the cycle, divided by 30, rounded half up to whole cents, and added to `next_invoice_adjustment_cents`. The days remaining are computed as the whole days from the current logical clock to `cycle_end_at` by floor division on a 86 400-second day, clamped below at 0 and above at 30. When the target fee is **less than or equal to** the current fee the change is a deferred downgrade: nothing is charged, `plan_id` and `monthly_fee_cents` are left exactly as they were, and only `pending_tier_plan_id` is set to the target plan. The switch then happens at the next cycle close. The practical consequence is worth stating plainly: the same two plans in the opposite direction produce completely different observable state, and every SLA target pinned on tickets created after an upgrade uses the new plan while tickets created after a downgrade request still use the old one.

A separate, un-guarded toggle sets `allow_overage` on the subscription, deciding whether a device claim beyond the included count converts into a per-device overage charge or is refused outright. Requesting cancellation moves the subscription from `ACTIVE` or from `PAST_DUE` into `CANCEL_PENDING`, clears `pending_tier_plan_id` to null, and bumps the version; the subscription does not actually become `CANCELLED` until the next cycle close, at which point gate 4 arms for every subsequent household-scoped mutating request.

**Closing a cycle** is the settlement operation, and it takes a single field `payment_outcome` whose value is either `SUCCEEDED` or `FAILED`. Its effect depends on the hop the subscription takes:

- From `ACTIVE` with `SUCCEEDED`, the subscription stays `ACTIVE`: `cycle_index` increments by 1, `cycle_start_at` advances to the prior `cycle_end_at` and `cycle_end_at` is recomputed 30 days later, the plan's `included_install_credits` are granted afresh by adding them to `install_credits_granted`, a recorded `pending_tier_plan_id` (if any) is applied by setting `plan_id` to it, re-pinning `monthly_fee_cents` from the new plan and clearing `pending_tier_plan_id` to null, and `credits_issued_cents_this_cycle` and `overage_charges_cents_this_cycle` are reset to 0.
- From `ACTIVE` with `FAILED`, the subscription moves to `PAST_DUE`: `cycle_index` increments by 1, `cycle_start_at` advances to the prior `cycle_end_at`, `cycle_end_at` is recomputed, and `credits_issued_cents_this_cycle` and `overage_charges_cents_this_cycle` are reset to 0. No fresh install credits are granted on this hop.
- From `PAST_DUE` with `SUCCEEDED`, the subscription returns to `ACTIVE`: `cycle_index` increments by 1, `cycle_start_at` advances to the prior `cycle_end_at`, fresh install credits equal to the plan's `included_install_credits` are granted, and `credits_issued_cents_this_cycle` and `overage_charges_cents_this_cycle` are reset to 0. This re-entry is what makes the subscription axis cyclic.
- From `PAST_DUE` with `FAILED`, the subscription moves to `SUSPENDED` and the failure cascades to the account: the owning household's `account_status` is set to `SUSPENDED`, its `suspended_at` is stamped with the logical-clock instant, and `Household.version` is bumped alongside `Subscription.version`.
- From `SUSPENDED` with `SUCCEEDED`, the subscription returns to `ACTIVE` and the cascade reverses: the owning household's `account_status` is set back to `ACTIVE` and its `suspended_at` cleared to null, `cycle_index` increments by 1, and both `Household.version` and `Subscription.version` are bumped by one each.
- From `CANCEL_PENDING`, with either `payment_outcome`, the subscription becomes `CANCELLED` and gate 4 arms.

The endpoint's overall contract is described as advancing the billing cycle and settling the invoice: rolling `cycle_index` and the cycle window forward by 30 days, granting `included_install_credits` and recomputing `install_credits_remaining`, resetting `credits_issued_cents_this_cycle`, `overage_charges_cents_this_cycle`, `next_invoice_credit_cents` and `next_invoice_adjustment_cents` to 0, applying `pending_tier_plan_id` when set, and advancing the lifecycle axis according to `payment_outcome` with the cascade onto `Household.account_status` on the hop from `PAST_DUE` to `SUSPENDED`. The hop-by-hop list above is the itemised statement of that contract. Whatever the hop, `Subscription.version` rises by exactly one, and a `payment_outcome` outside `SUCCEEDED` and `FAILED` is refused with `ERR_INVALID_ENUM`.

Subscriptions may be listed with optional `household_id`, `plan_id` and `pending_tier_plan_id` filters alongside `limit` and `offset` — the third filter is how an operator finds every household with a downgrade queued — and any single subscription may be read by id, returning the credit, overage and install-credit ledgers together. A single plan may be read by id.

### 3.3. The Catalog, Claiming a Device and the Onboarding Handshake

Before any hardware can be claimed it must exist in the **device catalog**, which like the plan table is configuration and carries neither `version` nor `updated_at`. A catalog model is defined by a `model_code` of 1 to 40 characters that is unique across all catalog rows, a human-readable `display_name`, a `device_class` drawn from `HUB`, `CAMERA`, `SENSOR`, `THERMOSTAT` and `LOCK`, a `serial_prefix` of 2 to 8 uppercase alphanumeric characters that every serial of this model must begin with, a `base_warranty_months` term of at least 0 whole months measured from the unit's purchase date, a boolean `requires_install` marking models whose units consume an install credit (or incur an install charge) when sold as an add-on, a boolean `manufacturer_service_only` that redirects in-warranty depot repairs to the manufacturer, an `msrp_cents` list price of at least 0 that is the base for both the bundle subtotal and the advance-replacement hold, and a `current_firmware_version` string stamped onto a newly activated unit of the model. Any single catalog model may be read by id; a `device_class` outside the five-member enumeration is refused with `ERR_INVALID_ENUM`.

Claiming a unit onto a household is an `Owner` or `PlatformAdmin` act and takes `household_id`, `catalog_entry_id`, `serial_number` and `purchase_date`. The `serial_number` is a manufacturer serial of 6 to 32 uppercase alphanumeric characters, globally unique across every `Device` row regardless of lifecycle state, and it must begin with the catalog entry's `serial_prefix`; a prefix mismatch is `ERR_SERIAL_MODEL_MISMATCH` and a serial already recorded on any other device — including one long since decommissioned — is `ERR_SERIAL_ALREADY_CLAIMED`. The `purchase_date` is supplied in `YYYY-MM-DD` form and is the anchor for all warranty arithmetic.

Three computations run at claim time, in this order. **First, the entitlement check.** Let *included* be the in-force plan's `included_device_count` and *before* be the household's current `entitled_device_count`; the post-claim count is *before* plus one. If that post-claim count is less than or equal to *included*, the device is inside the entitlement and `is_overage` is set false — note the boundary, so the claim that brings the count to exactly the included number is free. If the post-claim count exceeds *included* and the subscription's `allow_overage` is true, `is_overage` is set true. If the post-claim count exceeds *included* and `allow_overage` is false, the claim is refused with `ERR_DEVICE_CAP_EXCEEDED`.

**Second, the overage charge**, which runs only when the entitlement check returned an overage. The days remaining in the cycle are the whole days from the current logical clock to the subscription's `cycle_end_at`, obtained by floor division on an 86 400-second day, clamped below at 0 and above at 30. If at least 5 days remain, the charge is the plan's `overage_fee_cents_per_device` multiplied by the days remaining, divided by 30, rounded half up to whole cents; that amount is added both to `overage_charges_cents_this_cycle` and to `next_invoice_adjustment_cents`. If fewer than 5 days remain, nothing is charged now — but the device is still flagged `is_overage`, so the full per-device fee applies from the next cycle onward. The same unit on the same plan therefore costs a different number of cents depending only on where in the cycle it was claimed.

**Third, the warranty pin.** The base term is the catalog entry's `base_warranty_months`. If the household's subscription has `status` `ACTIVE` or `PAST_DUE` **and** the in-force plan's `warranty_extension_months` is greater than 0, the total term is the base months plus the extension months and `warranty_basis` is recorded as `TIER_EXTENDED`; otherwise the total term is the base months alone and `warranty_basis` is recorded as `BASE_ONLY`. The `warranty_expires_at` instant is then midnight UTC of the date obtained by adding that whole number of months to `purchase_date`, clamping to the last day of the target month when the target month has no such day-of-month — so a unit purchased on 31 January with a one-month term expires at midnight UTC on 28 February in a non-leap year. The instant is rendered in ISO 8601 UTC with three fractional digits and always at `00:00:00.000Z`. Because both the catalog entry and the plan are read at claim time, a later tier change never re-pins an existing device's warranty; conversely, the identical unit claimed on an extended plan rather than a base plan can flip a future RMA from `EXPIRED` to `IN_WARRANTY`.

The claim also mints the onboarding handshake. A single-use `activation_token` is generated and returned on the created row, and `activation_expires_at` is set to the claim instant plus 1440 minutes, which is 24 hours. The device is created with `lifecycle_status` `CLAIMED`, `firmware_status` `CURRENT`, `activation_attempts` 0, `activated_at` null and `firmware_version` unset, and the household's `entitled_device_count` together with the subscription's `overage_device_count` are recomputed.

Activation is the `Owner`'s echo of that token in the field `activation_code`, and it is the most branch-sensitive operation in the onboarding flow. Three rungs guard it in a fixed order. If the logical clock is at or after `activation_expires_at`, the attempt reports `ERR_ACTIVATION_TOKEN_EXPIRED` — and the expiry path still moves the row: `lifecycle_status` goes from `CLAIMED` to `RECLAIMABLE`, `activation_token` is cleared to null, `activation_attempts` is left exactly as it was, and `Device.version` rises by one. If the token has not expired, the attempt-cap rung is evaluated next: `activation_attempts` must be strictly below 3 before the attempt and, after a mismatching code, the post-increment value must still be strictly below 3. A device that already carries 3 recorded failures, or whose third failure this call would be, reports `ERR_ACTIVATION_ATTEMPTS_EXCEEDED`; on the third-failure path the row moves too, with `activation_attempts` set to 3, `lifecycle_status` moved from `CLAIMED` to `RECLAIMABLE`, `activation_token` cleared to null and `Device.version` bumped. Only then is the code itself compared: a `activation_code` that does not equal `activation_token` on a first or second failure reports `ERR_ACTIVATION_CODE_INVALID`, increments `activation_attempts` by one, leaves `lifecycle_status` at `CLAIMED` and bumps `Device.version`. The asymmetry is deliberate and must be implemented exactly: the first and second bad codes only bump the counter, while the third also moves the row. In every one of these cases the request answers with an error status even though the row was written, and in every case `Device.version` rises by exactly one.

A correct code succeeds: `lifecycle_status` moves from `CLAIMED` to `ACTIVE`, `activated_at` is stamped with the logical-clock instant, `firmware_version` is set to the catalog entry's `current_firmware_version`, `activation_token` is cleared to null, the household's `active_device_count` is recomputed and `Device.version` rises by one.

A device stranded in `RECLAIMABLE` is recovered by a `SupportAgent` or `PlatformAdmin`: the reclaim operation mints a fresh `activation_token`, sets `activation_expires_at` to the current logical-clock instant plus 1440 minutes, resets `activation_attempts` to 0 and returns `lifecycle_status` to `CLAIMED`, closing the onboarding loop `CLAIMED → RECLAIMABLE → CLAIMED`. Reclaim requested against a device in any other lifecycle state is refused with `ERR_RECLAIM_NOT_ELIGIBLE`.

Devices are listed with optional `household_id`, `catalog_entry_id`, `transfer_target_household_id` and `lifecycle_status` filters alongside `limit` and `offset`, and a single device may be read by id, returning both status axes and, while the unit is still unactivated, the `activation_token`.

### 3.4. Device Custody: Transfer and Decommission

Ownership of an activated device may be handed to another household in two steps. The offering step is an `Owner` act naming `target_household_id`; it requires the device to be `ACTIVE`, the target household's `account_status` to be `ACTIVE`, and no `RmaCase` on the device to be in `OPEN`, `ROUTED`, `ADVANCE_SHIPPED` or `AWAITING_RETURN`. An in-flight RMA case is reported as `ERR_RMA_IN_FLIGHT`; a target household that is not `ACTIVE`, like any other unmet transition precondition without a rung of its own, is reported as `ERR_INVALID_STATE`. On success `transfer_target_household_id` is set to the target and `lifecycle_status` moves from `ACTIVE` to `TRANSFER_PENDING`. The unit stays in the source household's `entitled_device_count` while it is pending, which is why `TRANSFER_PENDING` is one of the entitled states.

The accepting step is performed by an `Owner` of the receiving household. It requires the device to be in `TRANSFER_PENDING` and the acting member's `household_id` to equal the device's `transfer_target_household_id`; a member of any other household is refused. It also runs the receiving household's entitlement check: if moving the unit in would push the target household's `entitled_device_count` above the target plan's `included_device_count` while the target subscription's `allow_overage` is false, the acceptance is refused with `ERR_DEVICE_CAP_EXCEEDED`. On success `household_id` becomes the target household, `transfer_target_household_id` is cleared to null, `lifecycle_status` returns to `ACTIVE`, `entitled_device_count` and `active_device_count` are recomputed on **both** the source and the target households, and `is_overage` is recomputed against the target plan. The global entitled-device total is unchanged by the pair, which is the device-count conservation invariant of §2.10.

Decommissioning permanently retires a unit and is available from three lifecycle states, each with slightly different bookkeeping. From `CLAIMED`, the move to `DECOMMISSIONED` recomputes the household's `entitled_device_count`. From `RECLAIMABLE`, likewise. From `ACTIVE`, the move additionally requires that no `RmaCase` on the device is in `OPEN`, `ROUTED`, `ADVANCE_SHIPPED` or `AWAITING_RETURN` — otherwise `ERR_RMA_IN_FLIGHT` — and it recomputes `entitled_device_count` and `active_device_count` on the household, recomputes `overage_device_count` on the subscription, and sets every `PENDING` firmware rollout targeting the device to `BLOCKED_BY_SERVICE`. All three paths bump `Device.version` by one. `DECOMMISSIONED` is terminal: from that point gate 2 refuses every mutating request that resolves to the unit, and decommissioning is the only operation permitted to lower the global entitled-device total, which it lowers by exactly one.

### 3.5. The Support Ticket and Its Three Independent Axes

A ticket is raised by an `Owner`, a `Member` or a `SupportAgent`. The payload carries the `household_id`, a `severity` of `P1`, `P2` or `P3`, and a `summary` of 1 to 200 characters; it may additionally carry a `device_id` naming the unit under support and an `opened_by_member_id` naming the member who filed it. Both of the latter are optional: an account-level ticket has no device, and a ticket an agent opened on the customer's behalf has no opening member. A `severity` outside the three-member enumeration is refused with `ERR_INVALID_ENUM`, and a ticket naming a decommissioned device is refused by gate 2 with `ERR_DEVICE_DECOMMISSIONED`.

At creation the service reads the single `SubscriptionPlan` in force on the household — through the household's subscription — and **pins both SLA targets onto the ticket row**. `first_response_target_minutes` is set to the plan's `first_response_minutes_p1` when the severity is `P1`, `first_response_minutes_p2` when it is `P2`, and `first_response_minutes_p3` when it is `P3`. `onsite_resolution_target_minutes` is set to sixty times the plan's `onsite_resolution_hours_p1`, `onsite_resolution_hours_p2` or `onsite_resolution_hours_p3`, selected the same way — the plan states the onsite promise in hours and the ticket stores it in minutes. These two numbers are pinned once and never re-derived: a later tier change does not re-pin the targets of an existing ticket. If the household has no subscription, the ticket cannot be priced and the request is refused with `ERR_SUBSCRIPTION_NOT_FOUND`.

Every downstream comparison uses a single derived quantity, the **active target**. While `first_response_at` is null the active target is `first_response_target_minutes`; once `first_response_at` is set the active target is `onsite_resolution_target_minutes`.

The new row begins with `workflow_status` `NEW`, `sla_status` `WITHIN` and `dispatch_status` `NOT_REQUIRED`, with `first_response_at`, `resolved_at`, `closed_at`, `pause_started_at`, `survey_solicited_at` and `escalation_reason` all null, and with `sla_paused_minutes`, `sla_uncovered_minutes`, `sla_counted_minutes` and `remote_session_failure_count` all 0. The SLA clock starts at `created_at`. These three axes are genuinely independent: the workflow axis is advanced by agent and technician actions, the SLA axis is advanced only by clock evaluation and by the pause/resume pair — never by a workflow move on its own — and the dispatch axis tracks the onsite sub-workflow. A single request may move two or three of them, and when it does `Ticket.version` still rises by exactly one.

The workflow axis runs as follows. A `SupportAgent` records the first response with a `note`, which moves `NEW → TRIAGED`; that transition additionally requires `first_response_at` to still be null. Opening a remote troubleshooting session moves `TRIAGED → REMOTE_DIAG` or `REOPENED → REMOTE_DIAG`, and a further session opened while already in `REMOTE_DIAG` is a self-loop that keeps the ticket in `REMOTE_DIAG`; the self-loop is permitted only when no session of the ticket is still `IN_PROGRESS`. Parking the ticket on the customer moves `REMOTE_DIAG → AWAITING_CUSTOMER` and is permitted only while `pause_started_at` is null; the customer's reply moves `AWAITING_CUSTOMER → REMOTE_DIAG` and is permitted only while `pause_started_at` is not null. That pair may repeat any number of times. Completing a remote session with a resolving verdict moves `REMOTE_DIAG → RESOLVED`; completing one with a failing or hardware verdict may instead move `REMOTE_DIAG → DISPATCH_PENDING`, as §3.7 describes. Booking a visit moves `DISPATCH_PENDING → ONSITE`; cancelling or no-showing that visit moves `ONSITE → DISPATCH_PENDING`; completing it moves `ONSITE → RESOLVED`. From `RESOLVED` the ticket either closes or reopens.

Closing is a `SupportAgent` act on a `RESOLVED` ticket. It stamps `closed_at` with the logical-clock instant, moves `workflow_status` to `CLOSED`, and arms gate 3 for every subsequent ticket-scoped mutating request except survey submission. `CLOSED` is terminal on the workflow axis.

Reopening is a customer act — `Owner` or `Member` — on a `RESOLVED` ticket, carrying a `reason`. It is permitted only while the logical clock is strictly before `resolved_at` plus 168 hours, which is seven days; at or after that instant the request is refused with `ERR_REOPEN_WINDOW_CLOSED`. A successful reopen moves `workflow_status` to `REOPENED`, clears `resolved_at` to null and moves the SLA axis from `MET` back to `WITHIN`. Crucially it **leaves `survey_solicited_at` untouched**: the satisfaction window is anchored to the ticket's first resolution and a reopen does not restart it. From `REOPENED` the only way forward is a new remote session, which closes the ticket's outer loop `RESOLVED → REOPENED → REMOTE_DIAG`.

Tickets are listed with optional `household_id`, `device_id`, `opened_by_member_id` and `workflow_status` filters alongside `limit` and `offset`; a single ticket may be read by id and returns all three axes together with the pinned targets.

### 3.6. The SLA Clock, Breach Tiers and Service Credits

The SLA clock is not elapsed time. Every whole minute between the ticket's `created_at` and the evaluation instant is classified into exactly one of three buckets, and the classification runs in a fixed precedence so that no minute is counted twice. The evaluation instant is the earlier of the current logical clock and the ticket's `resolved_at` when `resolved_at` is set; when `resolved_at` is null the evaluation instant is simply the current logical clock. The total elapsed minutes are the whole minutes from `created_at` to that instant, by floor division on a 60-second minute.

A minute is classified **paused** when it lies inside one of the ticket's customer-wait segments. Segments are half-open, running from a `pause_started_at` instant up to but not including the resuming reply instant; the currently open segment, if `pause_started_at` is not null, runs to the evaluation instant. Failing that, a minute is classified **uncovered** when the plan's coverage window does not contain it. Everything else is classified **counted**. `sla_paused_minutes` is the number of paused minutes, `sla_uncovered_minutes` the number of uncovered minutes, and `sla_counted_minutes` is the total elapsed minutes less the paused minutes less the uncovered minutes. None of the three may be negative, and the three always sum back to the elapsed total, which is the ticket-minute conservation invariant.

Coverage has two variants and they diverge sharply. When the in-force plan's `coverage_mode` is `TWENTY_FOUR_SEVEN`, every minute is covered: `sla_uncovered_minutes` is always 0 and the counted minutes are simply the elapsed minutes less the paused minutes. When the `coverage_mode` is `BUSINESS_HOURS`, a minute counts only when its UTC minute-of-day is at or after minute 540 of the day — 09:00 UTC — and strictly before minute 1020 — 17:00 UTC. The window applies on **every calendar day including Saturdays and Sundays**; there is no weekend exclusion. The same wall-clock span therefore yields strictly fewer counted minutes under business-hours coverage than under round-the-clock coverage whenever it crosses the 17:00-to-09:00 UTC gap.

The clock partition is recomputed on the first-response settlement, on the customer's reply, on an explicit SLA evaluation, on the read-only SLA projection, on the completion of a remote session and on the completion of a visit. The read-only projection returns six fields and writes nothing: `sla_counted_minutes`, `sla_paused_minutes`, `sla_uncovered_minutes`, `total_elapsed_minutes`, `active_target_minutes` and `sla_status`.

Parking and resuming are what move minutes between buckets. Parking the ticket is a `SupportAgent` act that may carry an optional `note`; it sets `pause_started_at` to the logical-clock instant and moves the SLA axis to `PAUSED` — from `WITHIN` or from `AT_RISK`, either is permitted. The customer's reply is an `Owner` or `Member` act and carries a required `message`; it adds the whole minutes from `pause_started_at` to the current instant, by floor division on a 60-second minute, to `sla_paused_minutes`, clears `pause_started_at` to null and moves the SLA axis back to `WITHIN`. Note that a ticket that was `AT_RISK` before the pause returns to `WITHIN`, not to `AT_RISK`.

**At-risk detection.** An explicit SLA evaluation moves the axis from `WITHIN` to `AT_RISK` when `sla_counted_minutes` is at least eighty per cent of the active target and at the same time no greater than the active target. Both bounds are inclusive.

**Breach detection.** A breach requires `sla_counted_minutes` to be **strictly greater** than the active target; equality is not a breach. A first-response breach is recognised when the ticket's `first_response_at` is null at the moment of evaluation, or is being set by that very call, and the counted minutes exceed `first_response_target_minutes`; the axis moves to `BREACHED_FIRST_RESPONSE` from either `WITHIN` or `AT_RISK`. An onsite-resolution breach is recognised when `first_response_at` is not null and `resolved_at` is still null and the counted minutes exceed `onsite_resolution_target_minutes`; the axis moves to `BREACHED_ONSITE` from `WITHIN`, from `AT_RISK`, or from `CREDITED` — a ticket whose first-response breach was already credited can still breach the onsite target later, and a second credit is then issued if cap room remains.

**Breach tier and credit percentage.** The overage ratio is the counted minutes minus the active target, divided by the active target, and it is compared as a real number without rounding. A ratio of 0.25 or less is a `MINOR` breach carrying a credit of five per cent; a ratio above 0.25 and up to and including 1.00 is a `MAJOR` breach carrying fifteen per cent; a ratio strictly above 1.00 is a `SEVERE` breach carrying thirty per cent. Both tier boundaries are inclusive on their upper side.

**The credit base is where the two breach kinds diverge.** For a first-response breach the base is the subscription's `monthly_fee_cents` alone. For an onsite-resolution breach the base is `monthly_fee_cents` **plus** `overage_charges_cents_this_cycle`, so the identical breach tier on the identical plan yields a strictly larger credit whenever the household has booked overage in the current cycle. The uncapped amount is the base multiplied by the credit percentage, rounded half up to whole cents, and is recorded on the credit row as `uncapped_amount_cents`.

**The per-cycle cap** is then applied. The cycle cap is the floor of the subscription's `monthly_fee_cents` multiplied by 0.50 — half the monthly fee, rounded down. The cents already issued are the sum of `amount_cents` over the `ServiceCredit` rows whose `subscription_id` is this subscription and whose `cycle_index` equals the subscription's current `cycle_index`; rows from earlier cycles never count against the current cap, and because the aggregate is a plain sum the order in which credits were issued is irrelevant. Cap room is the cycle cap less the issued cents, clamped below at 0. The credit actually granted, `amount_cents`, is the smaller of the uncapped amount and the cap room. **A `ServiceCredit` row is created only when `amount_cents` is greater than zero.**

A credit row records the `household_id`, the `subscription_id`, the `ticket_id` that produced it, a `reason` of `SLA_FIRST_RESPONSE_BREACH`, `SLA_ONSITE_BREACH`, `CSAT_BREACH_COMPOUNDED` or `CSAT_GOODWILL`, a `breach_tier` of `MINOR`, `MAJOR` or `SEVERE` when the reason is one of the two SLA breaches and null for the two CSAT reasons, the `uncapped_amount_cents` and the granted `amount_cents`, the `cycle_index` at issuance to which the cap is scoped, and `applied_to_cycle_index`, which is always the issuing `cycle_index` plus one because credits land on the **next** invoice and never on the current one. Whenever a credit row is created, its `amount_cents` is added to the subscription's `credits_issued_cents_this_cycle` and to its `next_invoice_credit_cents`.

**Settling the first response.** The `SupportAgent`'s first-response call stamps `first_response_at` with the logical-clock instant, moves the workflow axis `NEW → TRIAGED`, and recomputes the clock partition to that instant. If the counted minutes exceed `first_response_target_minutes` the SLA axis moves to `BREACHED_FIRST_RESPONSE`, the breach tier and credit are computed, and a credit row with reason `SLA_FIRST_RESPONSE_BREACH` is created when the capped amount is above zero — after which the SLA axis moves on to `CREDITED`. When the capped amount is zero because the cycle cap is exhausted, no credit row is written, the axis stays at `BREACHED_FIRST_RESPONSE`, and the request still succeeds: the first-response settlement never reports `ERR_CREDIT_CAP_REACHED`. If the counted minutes do not exceed the target, the SLA axis is left at `WITHIN`.

**Explicit evaluation.** A `SupportAgent` or `PlatformAdmin` may evaluate a ticket's SLA at any time. The call recomputes `sla_counted_minutes`, `sla_paused_minutes` and `sla_uncovered_minutes`, then advances the SLA axis if and only if one of the transitions above has its preconditions satisfied — to `AT_RISK`, to `BREACHED_FIRST_RESPONSE` or to `BREACHED_ONSITE`, and onward to `CREDITED` when a credit row was created with a positive amount. When no listed transition applies the call still succeeds and simply leaves the axis where it was. Unlike the first-response settlement, this endpoint **does** enforce the cap rung: when a breach is detected and a credit would be due but the cycle's cap room is zero, the request is refused with `ERR_CREDIT_CAP_REACHED` and nothing is written.

**Meeting the target.** Completing a remote session with a resolving verdict, or completing an onsite visit, recomputes the clock and moves the SLA axis to `MET` when the axis was in `WITHIN` or `AT_RISK` and the counted minutes are less than or equal to `onsite_resolution_target_minutes`. Reopening the ticket moves the axis from `MET` back to `WITHIN`.

Service credits may be listed with optional `household_id`, `subscription_id` and `ticket_id` filters alongside `limit` and `offset`, and a single credit may be read by id, returning both its uncapped and its capped amount. There is no way to create a credit directly; credits exist only as the consequence of a breach settlement or a satisfaction survey.

### 3.7. Remote Troubleshooting and the Depth-Five Escalation Cascade

Remote troubleshooting is organised into sessions. A `SupportAgent` opens one against a ticket; the request carries no body. The created row records its `ticket_id`, the opening agent's opaque identifier as `agent_user_id`, a `session_index` that is the 1-based ordinal of this session within its ticket assigned by `created_at` ascending — in practice the count of prior sessions on the ticket plus one — a `started_at` stamped with the logical-clock instant, `status` `IN_PROGRESS`, `ended_at` null and `outcome` null. Opening a session is what drives the workflow axis `TRIAGED → REMOTE_DIAG` or `REOPENED → REMOTE_DIAG`, and successive attempts self-loop within `REMOTE_DIAG`; a second session may not be opened while one is still `IN_PROGRESS`, and an attempt to do so is refused with `ERR_INVALID_STATE`. Sessions may be listed with an optional `ticket_id` filter alongside `limit` and `offset`, and read singly by id.

Completing a session is the pivot of the whole support workflow. The agent supplies an `outcome` of `RESOLVED`, `FAILED` or `HARDWARE_FAULT` and may supply `diagnostic_notes`; a value outside those three is refused with `ERR_INVALID_ENUM`. Completion requires the session to be `IN_PROGRESS` and the owning ticket to be in `REMOTE_DIAG`.

The escalation rule reads as follows. When the `outcome` is `FAILED`, the ticket's `remote_session_failure_count` is incremented by one and escalation occurs when the **post-increment** value has reached 3; the escalation reason is `FAILURE_THRESHOLD`. The comparison is on the incremented value, so the third failed completion escalates and the second does not — the first and second failing verdicts leave `workflow_status` at `REMOTE_DIAG` and only bump the counter. When the `outcome` is `HARDWARE_FAULT`, escalation occurs immediately at any failure count and the escalation reason is `HARDWARE_FAULT`. When the `outcome` is `RESOLVED`, there is no escalation. Only the ticket's own sessions count; sessions of other tickets never enter the tally.

When escalation fires, a **five-hop cascade** runs inside the single completing request:

1. **Hop 1 — the session.** `outcome` is recorded, `ended_at` is stamped with the logical-clock instant, and `status` becomes `COMPLETED`.
2. **Hop 2 — the ticket.** On a failing verdict `remote_session_failure_count` is incremented; when the incremented count has reached 3, or whenever the verdict is `HARDWARE_FAULT`, `workflow_status` moves `REMOTE_DIAG → DISPATCH_PENDING`, `dispatch_status` moves `NOT_REQUIRED → REQUIRED`, and `escalation_reason` is set to `FAILURE_THRESHOLD` or `HARDWARE_FAULT` accordingly.
3. **Hop 3 — the device.** When the ticket's `device_id` is not null and that device's `lifecycle_status` is `ACTIVE`, the device moves `ACTIVE → SERVICE_HOLD`.
4. **Hop 4 — the rollouts.** Every `FirmwareRollout` targeting that device whose `status` is `PENDING` moves to `BLOCKED_BY_SERVICE`, and the device's `firmware_status` moves to `BLOCKED` where it stood at `UPDATE_PENDING`.
5. **Hop 5 — the campaign.** The ring counters of each affected `FirmwareCampaign` are recomputed, and a campaign in `RING_ACTIVE` whose current ring is left with no `PENDING` rollouts, while its ring failure rate is below its halt threshold, becomes `COMPLETED`.

A resolving verdict takes a different path: `workflow_status` moves `REMOTE_DIAG → RESOLVED`, `resolved_at` is stamped with the logical-clock instant, `survey_solicited_at` is stamped with the same instant **on the first resolution only** and is never overwritten by a later re-resolution, and the SLA axis is settled to `MET` when it stood in `WITHIN` or `AT_RISK` and the counted minutes are within `onsite_resolution_target_minutes`. `RemoteSession.version` rises by one on any completion.

### 3.8. Field Dispatch: Technicians, Slots, Visits and Fees

Field technicians are registered by a platform operator with a `full_name`, a `region_code` of exactly three uppercase letters naming the single dispatch region they serve, and a non-empty `skills` array whose elements are drawn from `HUB`, `CAMERA`, `SENSOR`, `THERMOSTAT` and `LOCK`; an element outside that set is refused with `ERR_INVALID_ENUM`. A newly registered technician has all four slot counters at 0: `total_slot_count`, `open_slot_count`, `booked_slot_count` and `blocked_slot_count`. Those counters are recomputed from the technician's slot rows — regardless of date, with no time-window filter — every time a slot is published, a visit is booked, rescheduled, cancelled or reported as a no-show, and they must always satisfy the slot-capacity conservation invariant: open plus booked plus blocked equals total.

Publishing availability is done by the technician themself or by a platform operator, supplying `start_at` and `end_at` at whole-minute precision with `end_at` strictly after `start_at`. The slot's own `region_code` is **copied from the owning technician** at creation and any value supplied in the request is ignored. A published slot begins with `status` `OPEN`, and publication raises the technician's `total_slot_count` and `open_slot_count` by one each. Slots may be listed with optional `technician_id` and `status` filters alongside `limit` and `offset`, and read singly by id.

Booking a visit is a `SupportAgent` act naming `ticket_id` and `slot_id`. Four business rungs guard it in this order, after the gates and the row-scope checks have passed. First, dispatch readiness: the ticket's `dispatch_status` must be `REQUIRED`, `RESCHEDULING` or `NO_SHOW`, and a ticket that never escalated — one still in `NEW`, `TRIAGED` or `REMOTE_DIAG` — reports `ERR_DISPATCH_NOT_REQUIRED` rather than a generic state error. Second, region: the slot's `region_code` must equal the ticket household's `region_code`, otherwise `ERR_SLOT_REGION_MISMATCH`. Third, availability: the slot's `status` must be `OPEN`, otherwise `ERR_SLOT_UNAVAILABLE`. Fourth, the travel buffer.

**The travel-buffer rule.** Slots are half-open intervals running from `start_at` inclusive to `end_at` exclusive. A candidate slot conflicts with an already-`BOOKED` slot of the *same* technician when the booked slot's start, moved 45 minutes earlier, is strictly before the candidate's end **and** the candidate's start is strictly before the booked slot's end, moved 45 minutes later. Both comparisons are strict, so exact buffer adjacency is legal: if a booked slot ends at 10:00, a candidate starting at exactly 10:45 is accepted while one starting at 10:44 is rejected. Only `BOOKED` slots of that technician participate; `OPEN` and `BLOCKED` slots never conflict. A conflict is reported as `ERR_SLOT_BUFFER_CONFLICT`.

A successful booking creates a `Visit` row in `SCHEDULED` with `scheduled_start_at` and `scheduled_end_at` copied from the occupied slot, `fee_kind` `NONE`, `fee_cents` 0, `fee_waived` false and `cancelled_at` null. The slot moves `OPEN → BOOKED` and the technician's `open_slot_count` falls by one while `booked_slot_count` rises by one. The ticket moves `DISPATCH_PENDING → ONSITE` on the workflow axis and `REQUIRED`, `RESCHEDULING` or `NO_SHOW` → `SCHEDULED` on the dispatch axis. Visits may be listed with optional `ticket_id` and `slot_id` filters alongside `limit` and `offset`, and read singly by id including any fee booked against them.

Rescheduling moves a scheduled visit to a different slot named by `new_slot_id`. The new slot is subject to the same region, availability and travel-buffer rungs as an original booking. The vacated slot is released to `OPEN`, the new slot is booked, `scheduled_start_at` and `scheduled_end_at` are re-copied from the new slot, and the slot counters are recomputed on the technicians owning both slots. The state-machine rule under which a booked slot returns to `OPEN` on a reschedule carries the precondition that the logical clock is at or before the visit's `scheduled_start_at` minus 24 hours. No fee is defined for a reschedule and `Visit.version` rises by one.

**Cancelling** a scheduled visit is available to a `SupportAgent` or the household's `Owner`, and its consequences hinge entirely on a 24-hour cutoff. The cutoff instant is the visit's `scheduled_start_at` minus 24 hours. When the cancellation happens at or before the cutoff it is an early cancellation: `fee_kind` stays `NONE`, `fee_cents` stays 0, `fee_waived` stays false, and the slot returns to `OPEN`, raising `open_slot_count` and lowering `booked_slot_count` by one each. When it happens strictly after the cutoff it is a late cancellation: `fee_kind` becomes `LATE_CANCEL`, the base fee is 4500 cents, and the slot moves to `BLOCKED` because the technician's time is consumed and cannot be resold, lowering `booked_slot_count` and raising `blocked_slot_count` by one each. **The `PRO` waiver applies here and only here**: if the household's in-force plan `tier` is `PRO`, `fee_waived` is set true and `fee_cents` is 0; otherwise `fee_waived` is false and `fee_cents` is the base fee. Whatever the amount, `fee_cents` is added to the subscription's `next_invoice_adjustment_cents`. In every case `cancelled_at` is stamped with the logical-clock instant, `Visit.status` becomes `CANCELLED`, the ticket moves `ONSITE → DISPATCH_PENDING` on the workflow axis and `SCHEDULED → RESCHEDULING` on the dispatch axis, and `Visit.version` rises by one.

**Reporting a no-show** is exclusively a `Technician` act and requires the logical clock to be at or after `scheduled_start_at`; earlier than that the request is refused with `ERR_VISIT_NOT_STARTED`. There is no cutoff test at all: `fee_kind` becomes `NO_SHOW` and `fee_cents` is 9000 cents, and **the `PRO` waiver does not apply to no-shows**, so a `PRO` household pays nothing for a late cancellation and the full 9000 cents for a no-show on the very same slot. The 9000 cents is added to `next_invoice_adjustment_cents`, the slot moves to `BLOCKED`, `Visit.status` becomes `NO_SHOW`, and the ticket moves `ONSITE → DISPATCH_PENDING` and `SCHEDULED → NO_SHOW`. From `NO_SHOW` or from `RESCHEDULING` a fresh visit may be booked, which is what makes the dispatch axis cyclic.

**Completing** a visit is likewise exclusively a `Technician` act. It requires the visit to be `SCHEDULED`, the acting technician's identity to equal the `technician_id` of the occupied slot, and the logical clock to be at or after `scheduled_start_at`; an early completion is refused with `ERR_VISIT_NOT_STARTED`. The technician may supply `completion_notes`. On success the visit becomes `COMPLETED` with `fee_kind` left at `NONE` and `fee_cents` left at 0; the occupied slot **stays `BOOKED`** — a completed visit does not free capacity; the ticket moves `ONSITE → RESOLVED` on the workflow axis and `SCHEDULED → COMPLETED` on the dispatch axis, with `resolved_at` stamped and `survey_solicited_at` stamped on the first resolution only; the SLA axis settles to `MET` when it stood in `WITHIN` or `AT_RISK` and the counted minutes are within `onsite_resolution_target_minutes`; and the device is released from service hold. That release is itself a small cascade: the device moves `SERVICE_HOLD → ACTIVE`, and every rollout of that device sitting in `BLOCKED_BY_SERVICE` whose owning campaign is `RING_ACTIVE` returns to `PENDING` with the device's `firmware_status` returning to `UPDATE_PENDING`. `Visit.version` rises by one.

### 3.9. Firmware Campaigns, Rings and Rollouts

Firmware is shipped in **campaigns**, and a campaign targets exactly one catalog model. A platform operator creates one by supplying the `catalog_entry_id`, a `kind` of either `SECURITY_MANDATORY` or `FEATURE_OPTIONAL`, the `target_firmware_version` string that a successful rollout stamps onto a device, and optionally a `halt_failure_rate_pct` — a number strictly greater than 0 and at most 1 which **defaults to 0.20 when omitted**. The campaign is created in `DRAFT` with `current_ring_index` 0, `ring_window_start_at` and `ring_window_end_at` null, and `ring_device_count`, `ring_failed_count` and `ring_failure_rate` all 0. The `kind` is what decides deferability and open-ticket blocking, and a value outside the two-member enumeration is refused with `ERR_INVALID_ENUM`. Campaigns may be listed with an optional `catalog_entry_id` filter alongside `limit` and `offset`, and read singly by id including the ring counters and the failure rate.

**Launching a ring** hands the operator an explicit device list. The request carries a `ring_index`, an array `device_ids`, and the ring's `window_start_at` and `window_end_at`. From `DRAFT` the campaign moves to `RING_ACTIVE`; from `RING_ACTIVE` it self-loops into the next ring, which requires that no rollout of the *current* ring is still `PENDING` and that the requested `ring_index` equals `current_ring_index` plus one. Every listed device must be `ACTIVE` on its lifecycle axis, must be a unit of the campaign's own catalog model, and must have a `firmware_status` that is neither `BLOCKED` nor `DEFERRED`; a listed device failing any of these is reported as `ERR_INVALID_STATE`, and the whole request is refused — a ring launch is all-or-nothing, and no rollout row is created when any listed device is unacceptable. Three further rungs apply per listed device: an in-flight RMA case on the device in `OPEN`, `ROUTED`, `ADVANCE_SHIPPED` or `AWAITING_RETURN` gives `ERR_RMA_IN_FLIGHT` regardless of the campaign's kind; for a `FEATURE_OPTIONAL` campaign only, a device with any ticket whose `workflow_status` is something other than `RESOLVED` or `CLOSED` gives `ERR_OPEN_TICKET_BLOCKS_ROLLOUT`, while a `SECURITY_MANDATORY` campaign skips that check entirely; and a window collision gives `ERR_ROLLOUT_WINDOW_OVERLAP`.

**The rollout-window rule is deliberately the opposite of the visit-slot rule.** Rollout windows are **closed** intervals running from `window_start_at` to `window_end_at` inclusive, and there is no buffer at all. A requested window conflicts with an existing `PENDING` rollout of the same device when the existing window's start is at or before the requested window's end **and** the requested window's start is at or before the existing window's end. Touching endpoints therefore *do* conflict: an existing `PENDING` rollout ending at 12:00 collides with a new window starting at exactly 12:00. Only rollouts in `PENDING` participate; rows in `APPLIED`, `ROLLED_BACK`, `DEFERRED`, `BLOCKED_BY_HALT` or `BLOCKED_BY_SERVICE` never conflict. A device already carrying an `UPDATE_PENDING` firmware status may therefore still be enrolled in a second campaign whose window does not collide; in that case no firmware-axis transition fires and only the new `PENDING` rollout row is created.

A successful launch sets `current_ring_index` to the requested `ring_index`, sets `ring_window_start_at` and `ring_window_end_at` to the requested window, creates one `FirmwareRollout` row per listed device in `PENDING` with `campaign_id`, `device_id`, a `ring_index` copied from the campaign's `current_ring_index`, `window_start_at` and `window_end_at` copied from the campaign's ring window, `retry_count` 0, `last_result` null, `deferred_until` null and `result_reported_at` null, moves each listed device's `firmware_status` from `CURRENT` or `ROLLED_BACK` to `UPDATE_PENDING`, and recomputes `ring_device_count`, `ring_failed_count` and `ring_failure_rate`. `FirmwareCampaign.version` rises by one. Rollouts may be listed with optional `campaign_id` and `device_id` filters alongside `limit` and `offset`, and read singly by id.

**Reporting a result** is a `Technician` or `PlatformAdmin` act carrying a single `result` of `SUCCESS` or `FAILURE`; anything else is `ERR_INVALID_ENUM`. It requires the rollout to be `PENDING` and the campaign to be `RING_ACTIVE`. Either way `last_result` is recorded and `result_reported_at` is stamped with the logical-clock instant. On `SUCCESS` the rollout becomes `APPLIED`, the device's firmware axis moves `UPDATE_PENDING → CURRENT`, and the device's `firmware_version` is stamped with the campaign's `target_firmware_version`. On `FAILURE` the rollout becomes `ROLLED_BACK` and the device's firmware axis moves `UPDATE_PENDING → ROLLED_BACK`, with `firmware_version` deliberately **left unchanged** because the rollback restores the prior image. `FirmwareRollout.version` rises by one.

**The ring failure rate and the halt.** After each result the campaign's counters are recomputed over the current ring only; earlier rings never re-enter the calculation. `ring_device_count` is the number of rollout rows of this campaign whose `ring_index` equals `current_ring_index`; `ring_failed_count` is the number of those rows whose `status` is `ROLLED_BACK`; and `ring_failure_rate` is `ring_failed_count` divided by `ring_device_count`, rounded half up to four decimal places, or exactly 0 when `ring_device_count` is 0. The campaign **halts** when the rounded rate is greater than or equal to its `halt_failure_rate_pct`. With the default threshold of 0.20, one failure out of five gives 0.2000 and halts, while one out of six gives 0.1667 and does not. Halting sets every rollout of the current ring still in `PENDING` to `BLOCKED_BY_HALT` and moves each of those devices' `firmware_status` to `BLOCKED`, and the campaign's `status` becomes `HALTED`.

**Resuming** a halted campaign returns it to `RING_ACTIVE`, sets every `BLOCKED_BY_HALT` rollout of the current ring back to `PENDING`, and returns each of those devices' `firmware_status` to `UPDATE_PENDING`. This re-entry is what makes the campaign axis cyclic.

**Completing.** Whenever an operation leaves a `RING_ACTIVE` campaign's current ring with no rollout in `PENDING` while `ring_failure_rate` is strictly below `halt_failure_rate_pct`, the campaign becomes `COMPLETED`, which is terminal. That condition can be reached by the last result report of the ring, by a deferral that takes the last `PENDING` row out of `PENDING`, and by the service-hold and decommission cascades that move `PENDING` rows to `BLOCKED_BY_SERVICE`.

**Deferring** is the household `Owner`'s privilege and carries a `defer_until` instant. It is permitted only when the owning campaign's `kind` is `FEATURE_OPTIONAL` and `defer_until` is at or before the logical clock plus 14 days; a mandatory security campaign, or a deferral reaching beyond that ceiling, is refused with `ERR_DEFER_NOT_ALLOWED`. The rollout must be `PENDING`. On success `deferred_until` is set to the requested instant, the rollout moves `PENDING → DEFERRED` and the device's firmware axis moves `UPDATE_PENDING → DEFERRED`.

**Retrying** is a `PlatformAdmin` act with no body. It applies to a rollout in `ROLLED_BACK` or in `DEFERRED`. The owning campaign must not be `HALTED`, otherwise `ERR_CAMPAIGN_HALTED`; only retry can ever reach that rung, because a halt blocks every `PENDING` rollout of the ring inside the same request, so result reporting and deferral fail the earlier from-state check instead, while a `ROLLED_BACK` rollout survives the halt and remains legally retryable on its own axis. The rollout's `retry_count` must then be strictly below 2, otherwise `ERR_RETRY_CAP_EXCEEDED` — the third retry is always refused. On success `retry_count` rises by one, the rollout returns to `PENDING`, `deferred_until` is cleared to null, the device's firmware axis returns to `UPDATE_PENDING` from either `ROLLED_BACK` or `DEFERRED`, and the ring counters are recomputed, which lowers `ring_failed_count` and therefore `ring_failure_rate` when the retried row had been a failure. The loop `PENDING → ROLLED_BACK → PENDING` is thus capped at two retries.

### 3.10. Add-On Orders: Bundle Pricing, Install Credits and Proration

A household grows its fleet by buying an add-on order, placed by a `BillingAdmin` or an `Owner`. The payload names the `household_id`, the `subscription_id` whose credits and invoice the order touches, the `expected_subscription_version` that guards it, and an ordered array `lines` of between 1 and 5 entries. Each line is an object carrying a `catalog_entry_id` referencing an existing catalog model and an integer `quantity` of at least 1. **The order of the lines in the request is pinned** and is the evaluation order for both the entitlement walk and the install-credit waterfall.

Pricing runs in six steps and the sequence is normative. In particular the discount tier is keyed on the subtotal **alone** and is deliberately *not* recomputed after the install charge or the proration is added, even though both raise the amount the customer pays.

**Step 1 — subtotal.** `subtotal_cents` is the sum over the lines of the catalog entry's `msrp_cents` multiplied by that line's `quantity`.

**Step 2 — bundle discount.** `bundle_discount_pct` is 0.15 when `subtotal_cents` is at least 50 000 cents, otherwise 0.10 when it is at least 20 000 cents, otherwise 0. Both thresholds are inclusive, so a subtotal of exactly 20 000 cents earns ten per cent. `bundle_discount_cents` is `subtotal_cents` multiplied by `bundle_discount_pct`, rounded half up to whole cents, and `discounted_subtotal_cents` is `subtotal_cents` less `bundle_discount_cents`.

**Step 3 — the install-credit waterfall.** Only units whose catalog model has `requires_install` true participate; units of non-install models are skipped entirely and never consume a credit. The participating units are expanded one row per unit and sorted by the model's `msrp_cents` **descending**, breaking ties by the line's position in the request ascending and then by the unit's index within its line ascending — the most expensive installation is covered first. The available credits are the subscription's `install_credits_remaining`. Walking the sorted units, each unit consumes one credit while credits remain. `install_credits_applied` is the number consumed; the subscription's `install_credits_consumed` rises by that number and `install_credits_remaining` is recomputed as `install_credits_granted` less `install_credits_consumed`, never dropping below zero.

**Step 4 — the install charge.** The uncovered units are the participating units less those covered, and `install_charge_cents` is 12 900 cents per uncovered unit.

**Step 5 — proration.** The days remaining in the cycle are the whole days from the current logical clock to `cycle_end_at`, by floor division on an 86 400-second day, clamped below at 0 and above at 30. Let *included* be the plan's `included_device_count` and let a running counter start at the household's current `entitled_device_count`. Walking the lines **in request order**, and the units within each line in turn, the counter is raised by one per unit and the unit is recorded as extra whenever the raised counter exceeds *included*; the per-line count of extras is retained. `monthly_delta_cents` is the plan's `overage_fee_cents_per_device` multiplied by the total number of extras across all lines. If at least 5 days remain, `proration_mode` is `MID_CYCLE_PRORATED` and `proration_cents` is the sum over lines of the value obtained by taking `overage_fee_cents_per_device`, multiplying by that line's extras, multiplying by the days remaining, dividing by 30 and **rounding each line half up to whole cents before summing** — summing first and rounding once at the end is a different and incorrect number. If fewer than 5 days remain, `proration_mode` is `NEXT_CYCLE_FULL` and `proration_cents` is 0; `monthly_delta_cents` is still recorded on the order and takes effect from the next cycle. The same basket on the same plan therefore produces a different `order_total_cents` depending only on where in the cycle it was placed.

**Step 6 — the total.** `order_total_cents` is `discounted_subtotal_cents` plus `install_charge_cents` plus `proration_cents`, with no further rounding, and that total is added to the subscription's `next_invoice_adjustment_cents`.

The entitlement cap is enforced on placement as a projection: if the units in the order would push the household's `entitled_device_count` above the plan's `included_device_count` while the subscription's `allow_overage` is false, the order is refused with `ERR_DEVICE_CAP_EXCEEDED`. The created order begins with `status` `PLACED` and an empty `fulfilled_device_ids`, and placing it bumps `Subscription.version` by one. Orders may be listed with optional `household_id` and `subscription_id` filters alongside `limit` and `offset`, and read singly by id with the full price breakdown.

**Fulfilment** is a `BillingAdmin` or `PlatformAdmin` act carrying `serial_numbers` and a `purchase_date`. It requires the order to be `PLACED` and the household's subscription to be in `ACTIVE` or `PAST_DUE`. One `Device` row is created in `CLAIMED` per ordered unit, walking the lines in the pinned request order and the units within each line in turn, consuming the entries of `serial_numbers` positionally in that same order. Each created device has the warranty pin of §3.3 applied to it — base term from its catalog model, extended when the subscription is `ACTIVE` or `PAST_DUE` and the plan grants a positive `warranty_extension_months`, with `warranty_basis` recorded accordingly. The new device ids are recorded in the order's `fulfilled_device_ids`, the household's `entitled_device_count` and the subscription's `overage_device_count` are recomputed, the order moves `PLACED → FULFILLED`, and `AddOnOrder.version` rises by one. The serial-prefix rung and the serial-uniqueness rung named in §2.9 are scoped to device claiming and are not part of the fulfilment path.

### 3.11. Warranty, RMA Routing and the Advance-Replacement Hold

When a unit is genuinely broken a `SupportAgent` opens an **RMA case** against it. The request names the `device_id`, carries the `expected_device_version` that guards it, and may name the `ticket_id` that surfaced the fault; a walk-up RMA with no originating ticket simply omits it. Opening a case bumps `Device.version` by one, which is precisely why the guard exists: a second case genuinely supersedes the first, so without the version check a caller acting on a stale view of the device would silently succeed.

Three computations run at creation, in this order. **Warranty state** is decided against the logical clock with a strict comparison: the case's `warranty_state` is `IN_WARRANTY` when the clock is strictly before the device's `warranty_expires_at`, and `EXPIRED` otherwise — a case opened at exactly the expiry instant is `EXPIRED`. The remaining warranty days are the whole days from the clock to `warranty_expires_at` by floor division on an 86 400-second day, clamped below at 0.

**Routing** then selects `routing_target` by taking the first matching branch of an ordered list; the ordering is normative and no later branch may pre-empt an earlier one.

1. If the warranty state is `EXPIRED`, the target is `CUSTOMER_PAID_DEPOT`.
2. Otherwise, if the in-force plan's `advance_replacement_eligible` is true and the model's `device_class` is `HUB`, the target is `ADVANCE_REPLACEMENT`.
3. Otherwise, if the in-force plan's `advance_replacement_eligible` is true, the model's `device_class` is `CAMERA` or `LOCK`, **and** the remaining warranty days are at least 30, the target is `ADVANCE_REPLACEMENT`. Hubs carry no such floor; cameras and locks do.
4. Otherwise, if the model's `manufacturer_service_only` is true, the target is `MANUFACTURER`.
5. Otherwise the target is `IN_HOUSE_DEPOT`.

**The hold** is computed only when the target is `ADVANCE_REPLACEMENT`: `hold_amount_cents` is the model's `msrp_cents` multiplied by 0.60, rounded half up to whole cents, and `hold_state` is set to `HELD`. On every other target `hold_amount_cents` is 0 and `hold_state` stays `NONE`. Creation also supersedes: any prior case on the same device whose `status` is `OPEN` or `ROUTED` moves to `SUPERSEDED`, and the new case records that prior case's id in its own `supersedes_rma_id`. Within the creating request the new case walks `OPEN → ROUTED`, so a freshly created case is returned in `ROUTED`.

From `ROUTED` the case forks on its routing target. **The depot and manufacturer branches never ship an advance unit and skip the hold sub-path entirely**: recording receipt of the faulty unit on a case in `ROUTED` whose target is `MANUFACTURER`, `IN_HOUSE_DEPOT` or `CUSTOMER_PAID_DEPOT` stamps `returned_at`, leaves `hold_state` at `NONE`, and closes the case outright.

**The advance-replacement branch** is longer. Shipping the replacement is refused with `ERR_ADVANCE_REPLACEMENT_NOT_ELIGIBLE` unless `routing_target` is `ADVANCE_REPLACEMENT`, and requires the case to be `ROUTED`. On success `shipped_at` is stamped with the logical-clock instant, `return_deadline_at` is computed as `shipped_at` plus 14 days, the case walks `ROUTED → ADVANCE_SHIPPED → AWAITING_RETURN` inside the one request, and the device moves `ACTIVE → SUSPENDED_RMA`. Both `RmaCase.version` and `Device.version` rise by exactly one each.

While the case is `AWAITING_RETURN`, recording receipt of the faulty unit is permitted only while the logical clock is at or before `return_deadline_at`. It stamps `returned_at`, moves `hold_state` from `HELD` to `RELEASED` — leaving `next_invoice_adjustment_cents` untouched, because a released hold is never billed — moves the case to `RETURN_RECEIVED`, and returns the device `SUSPENDED_RMA → ACTIVE`.

Closing the return window handles both endings. On a case in `RETURN_RECEIVED` it simply moves the case to `CLOSED` without charging anything. On a case still in `AWAITING_RETURN` it requires the logical clock to be **strictly after** `return_deadline_at`; called at or before the deadline it is refused with `ERR_RETURN_WINDOW_OPEN`. Past the deadline the case walks `AWAITING_RETURN → RETURN_WINDOW_EXPIRED → CHARGED → CLOSED` inside the one request: `hold_state` moves from `HELD` to `CHARGED`, `hold_amount_cents` is added to the subscription's `next_invoice_adjustment_cents`, the device returns `SUSPENDED_RMA → ACTIVE`, and `Subscription.version` rises by one alongside the single bump of `RmaCase.version`.

`CLOSED` and `SUPERSEDED` are the two terminal states of an RMA case. Cases may be listed with optional `device_id`, `ticket_id` and `supersedes_rma_id` filters alongside `limit` and `offset` — the third filter is how an operator traces a supersession chain — and read singly by id including the hold ledger.

### 3.12. Satisfaction Surveys and Goodwill Credits

Once a ticket has been resolved for the first time the household may rate it, and exactly once. The survey is submitted by an `Owner` or a `Member`, carrying an integer `score` between 1 and 5 inclusive and an optional free-text `comment`. Survey submission is the one ticket-scoped mutation exempt from gate 3, so a ticket that has already been closed can still be rated. Two rungs guard it: a second submission for the same ticket is refused with `ERR_SURVEY_ALREADY_SUBMITTED`, and a submission whose ticket has a null `survey_solicited_at`, or that arrives at or after `survey_solicited_at` plus 72 hours, is refused with `ERR_SURVEY_WINDOW_CLOSED`. The created row records its `ticket_id`, the `score`, the `comment`, a `submitted_at` stamped with the logical-clock instant, and a `window_closes_at` equal to the ticket's `survey_solicited_at` plus 72 hours. Because a reopen never rewrites `survey_solicited_at`, the window is measured from the ticket's very first resolution however many times it has since been reopened and re-resolved.

A low score can pay. A score of 2 or lower is **low**; a score of 3, 4 or 5 is not. The ticket's SLA axis is read at *submission* time, not at resolution time, and counts as **breached** when `sla_status` is `BREACHED_FIRST_RESPONSE`, `BREACHED_ONSITE` or `CREDITED`. Three outcomes follow, in this order of evaluation:

- If the score is not low, `credit_variant` is `NONE` and the uncapped amount is 0.
- Otherwise, if the ticket's SLA axis is breached, `credit_variant` is `BREACH_COMPOUNDED` and the uncapped amount is the subscription's `monthly_fee_cents` multiplied by 0.10, rounded half up to whole cents. This pays ten per cent of the monthly fee **on top of** any SLA breach credit already issued this cycle, so the per-cycle cap is what limits the stack.
- Otherwise, if the household's in-force plan `tier` is `PRO`, `credit_variant` is `GOODWILL` and the uncapped amount is `monthly_fee_cents` multiplied by 0.05, rounded half up to whole cents.
- Otherwise `credit_variant` is `NONE` and the uncapped amount is 0 — a `BASIC` or `PLUS` household with a low score and no SLA breach receives nothing, so identical survey inputs diverge on plan tier alone.

The survey's `credit_cents` is the smaller of the uncapped amount and the cycle's remaining cap room, computed exactly as in §3.6, and a `ServiceCredit` row with reason `CSAT_BREACH_COMPOUNDED` or `CSAT_GOODWILL` is created only when that capped amount is greater than zero, with `breach_tier` left null. When a row is created, its `amount_cents` is added to the subscription's `credits_issued_cents_this_cycle` and to `next_invoice_credit_cents`, and its `applied_to_cycle_index` is the current `cycle_index` plus one. Surveys may be listed with an optional `ticket_id` filter alongside `limit` and `offset`, and read singly by id.

---

## 4. Endpoint Definitions

Every path below is absolute and already includes the `/smart-home-support` prefix. Endpoints that bring a brand-new resource into existence answer with HTTP 201; every other successful call answers with HTTP 200. Note two deliberate exceptions to the intuitive reading: launching a firmware ring answers 200 even though it creates rollout rows, because the resource returned is the campaign, and closing an RMA return window answers 200 even though the case may traverse three states inside the call. The table below is a routing summary only — the request payload, the response payload and the side effects of each operation are specified in the narratives of §2 and §3, and readers must return there to reconstruct the full contract.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/smart-home-support/households` | Register a household. | `PlatformAdmin` |
| GET | `/smart-home-support/households/{id}` | Read one household including its derived device counts. | `PlatformAdmin`, `SupportAgent`, `Owner`, `Member`, `BillingAdmin` |
| POST | `/smart-home-support/households/{id}/account-status` | Suspend, reinstate or close a household account. | `PlatformAdmin` |
| POST | `/smart-home-support/households/{id}/members` | Add a member to a household. | `PlatformAdmin`, `Owner` |
| GET | `/smart-home-support/household-members` | List household members, optionally filtered by household. | `PlatformAdmin`, `SupportAgent`, `Owner`, `Member`, `BillingAdmin` |
| GET | `/smart-home-support/household-members/{id}` | Read one household member. | `PlatformAdmin`, `SupportAgent`, `Owner`, `Member`, `BillingAdmin` |
| POST | `/smart-home-support/subscription-plans` | Create a subscription plan (configuration entity, no version field). | `PlatformAdmin` |
| GET | `/smart-home-support/subscription-plans/{id}` | Read one subscription plan. | `PlatformAdmin`, `SupportAgent`, `Owner`, `BillingAdmin` |
| POST | `/smart-home-support/subscriptions` | Start a subscription for a household. | `PlatformAdmin` |
| GET | `/smart-home-support/subscriptions` | List subscriptions, filterable by household, in-force plan, or pending downgrade plan. | `PlatformAdmin`, `SupportAgent`, `Owner`, `BillingAdmin` |
| GET | `/smart-home-support/subscriptions/{id}` | Read one subscription including credit, overage and install-credit ledgers. | `PlatformAdmin`, `SupportAgent`, `Owner`, `BillingAdmin` |
| POST | `/smart-home-support/subscriptions/{id}/change-tier` | Change tier. | `BillingAdmin`, `PlatformAdmin` |
| POST | `/smart-home-support/subscriptions/{id}/set-overage-policy` | Toggle whether device claims beyond the included count convert to overage or are rejected. | `BillingAdmin`, `PlatformAdmin` |
| POST | `/smart-home-support/subscriptions/{id}/cancel` | Request cancellation; the subscription moves to CANCEL_PENDING and becomes CANCELLED at the next close-cycle. | `Owner`, `PlatformAdmin` |
| POST | `/smart-home-support/subscriptions/{id}/close-cycle` | Advance the billing cycle and settle the invoice. | `PlatformAdmin` |
| POST | `/smart-home-support/device-catalog` | Create a catalog model (configuration entity, no version field). | `PlatformAdmin` |
| GET | `/smart-home-support/device-catalog/{id}` | Read one catalog model. | `PlatformAdmin`, `SupportAgent`, `Owner`, `BillingAdmin` |
| POST | `/smart-home-support/devices/claim` | Claim a device onto a household. | `Owner`, `PlatformAdmin` |
| GET | `/smart-home-support/devices` | List devices, filterable by household, model, pending transfer target, or lifecycle state. | `PlatformAdmin`, `SupportAgent`, `Owner`, `Member`, `BillingAdmin` |
| GET | `/smart-home-support/devices/{id}` | Read one device including both status axes and the activation token when still unactivated. | `PlatformAdmin`, `SupportAgent`, `Owner`, `Member`, `BillingAdmin` |
| POST | `/smart-home-support/devices/{id}/activate` | Complete the onboarding handshake by echoing the activation token. | `Owner` |
| POST | `/smart-home-support/devices/{id}/reclaim` | Recover a device stuck unactivated: re-mint the token, reset the attempt counter and return it to CLAIMED. | `SupportAgent`, `PlatformAdmin` |
| POST | `/smart-home-support/devices/{id}/decommission` | Permanently retire a device and free its entitlement slot. | `Owner`, `PlatformAdmin` |
| POST | `/smart-home-support/devices/{id}/transfer` | Offer ownership of a device to another household. | `Owner` |
| POST | `/smart-home-support/devices/{id}/accept-transfer` | Accept an offered device into the acting member's household; runs the target household's entitlement cap check. | `Owner` |
| POST | `/smart-home-support/tickets` | Open a support ticket; pins both SLA targets from the in-force plan and the severity. | `Owner`, `Member`, `SupportAgent` |
| GET | `/smart-home-support/tickets` | List tickets, filterable by household, device, opening member or workflow state. | `PlatformAdmin`, `SupportAgent`, `Owner`, `Member`, `BillingAdmin` |
| GET | `/smart-home-support/tickets/{id}` | Read one ticket with all three status axes and the pinned SLA targets. | `PlatformAdmin`, `SupportAgent`, `Owner`, `Member`, `BillingAdmin` |
| GET | `/smart-home-support/tickets/{id}/sla` | Read-only projection of the SLA clock partition at the current logical-clock instant; writes nothing. | `PlatformAdmin`, `SupportAgent`, `Owner` |
| POST | `/smart-home-support/tickets/{id}/first-response` | Record the first agent response and settle the first-response SLA. | `SupportAgent` |
| POST | `/smart-home-support/tickets/{id}/await-customer` | Park the ticket on the customer and PAUSE the SLA clock. | `SupportAgent` |
| POST | `/smart-home-support/tickets/{id}/customer-reply` | Customer replies; the paused segment is banked and the SLA clock RESUMES. | `Owner`, `Member` |
| POST | `/smart-home-support/tickets/{id}/remote-sessions` | Open a remote troubleshooting session on the ticket. | `SupportAgent` |
| POST | `/smart-home-support/tickets/{id}/sla-evaluate` | Evaluate the SLA clock against the active target and advance the sla axis, issuing a breach credit when one is due. | `SupportAgent`, `PlatformAdmin` |
| POST | `/smart-home-support/tickets/{id}/close` | Close a resolved ticket. | `SupportAgent` |
| POST | `/smart-home-support/tickets/{id}/reopen` | Reopen a resolved ticket inside the 168-hour reopen window. | `Owner`, `Member` |
| POST | `/smart-home-support/tickets/{id}/survey` | Submit the one-and-only CSAT survey for the ticket, inside the 72-hour window. | `Owner`, `Member` |
| GET | `/smart-home-support/remote-sessions` | List remote sessions, filterable by ticket. | `PlatformAdmin`, `SupportAgent`, `Owner` |
| GET | `/smart-home-support/remote-sessions/{id}` | Read one remote session. | `PlatformAdmin`, `SupportAgent`, `Owner` |
| POST | `/smart-home-support/remote-sessions/{id}/complete` | Close a remote session with a verdict. | `SupportAgent` |
| POST | `/smart-home-support/technicians` | Register a field technician. | `PlatformAdmin` |
| GET | `/smart-home-support/technicians/{id}` | Read one technician including the four slot counters used by slot_capacity_conservation. | `PlatformAdmin`, `SupportAgent`, `Technician` |
| POST | `/smart-home-support/technicians/{id}/visit-slots` | Publish an availability slot. | `Technician`, `PlatformAdmin` |
| GET | `/smart-home-support/visit-slots` | List slots, filterable by technician and capacity state. | `PlatformAdmin`, `SupportAgent`, `Technician`, `Owner` |
| GET | `/smart-home-support/visit-slots/{id}` | Read one slot. | `PlatformAdmin`, `SupportAgent`, `Technician`, `Owner` |
| POST | `/smart-home-support/visits` | Book an onsite visit for an escalated ticket into an OPEN slot, enforcing region match and the travel-buffer overlap rule. | `SupportAgent` |
| GET | `/smart-home-support/visits` | List visits, filterable by ticket or slot. | `PlatformAdmin`, `SupportAgent`, `Technician`, `Owner` |
| GET | `/smart-home-support/visits/{id}` | Read one visit including any fee booked against it. | `PlatformAdmin`, `SupportAgent`, `Technician`, `Owner` |
| POST | `/smart-home-support/visits/{id}/reschedule` | Move a scheduled visit to a different OPEN slot; the vacated slot returns to OPEN. | `SupportAgent` |
| POST | `/smart-home-support/visits/{id}/cancel` | Cancel a scheduled visit; late cancellations inside the 24-hour cutoff charge a fee and BLOCK the slot. | `SupportAgent`, `Owner` |
| POST | `/smart-home-support/visits/{id}/complete` | Technician completes the onsite visit; resolves the ticket and releases the device from SERVICE_HOLD. | `Technician` |
| POST | `/smart-home-support/visits/{id}/no-show` | Technician reports the customer was absent; charges the no-show fee (never waived) and BLOCKS the slot. | `Technician` |
| POST | `/smart-home-support/firmware-campaigns` | Create a firmware campaign in DRAFT. | `PlatformAdmin` |
| GET | `/smart-home-support/firmware-campaigns` | List campaigns, filterable by catalog model. | `PlatformAdmin`, `SupportAgent` |
| GET | `/smart-home-support/firmware-campaigns/{id}` | Read one campaign including the ring counters and failure rate. | `PlatformAdmin`, `SupportAgent` |
| POST | `/smart-home-support/firmware-campaigns/{id}/launch-ring` | Launch a wave of the campaign over an explicit device list. | `PlatformAdmin` |
| POST | `/smart-home-support/firmware-campaigns/{id}/resume` | Resume a HALTED campaign, returning its BLOCKED_BY_HALT rollouts to PENDING. | `PlatformAdmin` |
| GET | `/smart-home-support/firmware-rollouts` | List rollouts, filterable by campaign or device. | `PlatformAdmin`, `SupportAgent`, `Technician`, `Owner` |
| GET | `/smart-home-support/firmware-rollouts/{id}` | Read one rollout. | `PlatformAdmin`, `SupportAgent`, `Technician`, `Owner` |
| POST | `/smart-home-support/firmware-rollouts/{id}/report-result` | Report the outcome of a rollout. | `Technician`, `PlatformAdmin` |
| POST | `/smart-home-support/firmware-rollouts/{id}/defer` | Customer defers an optional feature update. | `Owner` |
| POST | `/smart-home-support/firmware-rollouts/{id}/retry` | Return a ROLLED_BACK or DEFERRED rollout to PENDING; capped at 2 retries. | `PlatformAdmin` |
| POST | `/smart-home-support/addon-orders` | Price and place a multi-line add-on device order. | `BillingAdmin`, `Owner` |
| GET | `/smart-home-support/addon-orders` | List add-on orders, filterable by household or subscription. | `PlatformAdmin`, `BillingAdmin`, `Owner` |
| GET | `/smart-home-support/addon-orders/{id}` | Read one add-on order with the full price breakdown. | `PlatformAdmin`, `BillingAdmin`, `Owner` |
| POST | `/smart-home-support/addon-orders/{id}/fulfill` | Ship the order: create one CLAIMED Device per ordered unit with the supplied serials. | `BillingAdmin`, `PlatformAdmin` |
| POST | `/smart-home-support/rma-cases` | Open an RMA and route it. | `SupportAgent` |
| GET | `/smart-home-support/rma-cases` | List RMA cases, filterable by device, ticket, or the case they superseded. | `PlatformAdmin`, `SupportAgent`, `Owner` |
| GET | `/smart-home-support/rma-cases/{id}` | Read one RMA case including the hold ledger. | `PlatformAdmin`, `SupportAgent`, `Owner` |
| POST | `/smart-home-support/rma-cases/{id}/ship-advance-replacement` | Ship the advance replacement unit and start the 14-day return window. | `SupportAgent` |
| POST | `/smart-home-support/rma-cases/{id}/receive-return` | Record receipt of the faulty unit; releases the hold when one is held. | `SupportAgent` |
| POST | `/smart-home-support/rma-cases/{id}/close-return-window` | Close the return window. | `SupportAgent` |
| GET | `/smart-home-support/surveys` | List satisfaction surveys, filterable by ticket. | `PlatformAdmin`, `SupportAgent`, `Owner` |
| GET | `/smart-home-support/surveys/{id}` | Read one satisfaction survey. | `PlatformAdmin`, `SupportAgent`, `Owner` |
| GET | `/smart-home-support/service-credits` | List service credits, filterable by household, subscription or ticket. | `PlatformAdmin`, `BillingAdmin`, `SupportAgent`, `Owner` |
| GET | `/smart-home-support/service-credits/{id}` | Read one service credit including its uncapped and capped amounts. | `PlatformAdmin`, `BillingAdmin`, `SupportAgent`, `Owner` |
| POST | `/smart-home-support/_clock/set_current_utc` | Set the server's logical clock. | `PlatformAdmin` |

---

## 5. Error Code Catalogue

Every error response carries the envelope of §2.2 with `response_type` set to `error` and the identifier below in `data.error_id`. The trigger condition for each identifier is stated in the narrative that governs it — the validation ladder of §2.9, the gate list of §2.8, or the workflow subsection of §3 that guards the operation.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_ROW_SCOPE_DENIED` | 403 |
| `ERR_HOUSEHOLD_NOT_FOUND` | 404 |
| `ERR_MEMBER_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_CATALOG_ENTRY_NOT_FOUND` | 404 |
| `ERR_DEVICE_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 |
| `ERR_SLOT_NOT_FOUND` | 404 |
| `ERR_VISIT_NOT_FOUND` | 404 |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_ROLLOUT_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_RMA_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ACCOUNT_SUSPENDED` | 403 |
| `ERR_DEVICE_DECOMMISSIONED` | 409 |
| `ERR_TICKET_CLOSED` | 409 |
| `ERR_SUBSCRIPTION_CANCELLED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SERIAL_MODEL_MISMATCH` | 422 |
| `ERR_SERIAL_ALREADY_CLAIMED` | 409 |
| `ERR_ACTIVATION_TOKEN_EXPIRED` | 409 |
| `ERR_ACTIVATION_ATTEMPTS_EXCEEDED` | 409 |
| `ERR_ACTIVATION_CODE_INVALID` | 422 |
| `ERR_RECLAIM_NOT_ELIGIBLE` | 409 |
| `ERR_RMA_IN_FLIGHT` | 409 |
| `ERR_OPEN_TICKET_BLOCKS_ROLLOUT` | 409 |
| `ERR_ROLLOUT_WINDOW_OVERLAP` | 409 |
| `ERR_CAMPAIGN_HALTED` | 409 |
| `ERR_DEFER_NOT_ALLOWED` | 409 |
| `ERR_RETRY_CAP_EXCEEDED` | 409 |
| `ERR_DISPATCH_NOT_REQUIRED` | 409 |
| `ERR_SLOT_REGION_MISMATCH` | 422 |
| `ERR_SLOT_UNAVAILABLE` | 409 |
| `ERR_SLOT_BUFFER_CONFLICT` | 409 |
| `ERR_VISIT_NOT_STARTED` | 409 |
| `ERR_REOPEN_WINDOW_CLOSED` | 409 |
| `ERR_SURVEY_ALREADY_SUBMITTED` | 409 |
| `ERR_SURVEY_WINDOW_CLOSED` | 409 |
| `ERR_ADVANCE_REPLACEMENT_NOT_ELIGIBLE` | 409 |
| `ERR_RETURN_WINDOW_OPEN` | 409 |
| `ERR_DEVICE_CAP_EXCEEDED` | 409 |
| `ERR_CREDIT_CAP_REACHED` | 409 |
