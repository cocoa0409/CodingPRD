# Internet Broadband Provisioning API — Product Requirements Document

## 1. Introduction

This document specifies the Internet/Broadband Service Provisioning API, the system of record for everything that happens between the moment a prospective subscriber checks whether their street can even receive service and the moment a departing subscriber's final invoice is settled. In between sit a long chain of operational realities that a residential broadband operator must coordinate: confirming that the plant at a given address can carry the speed a customer wants, dispatching a field technician (or shipping a self-install kit) inside a finite scheduling window, leasing a modem or gateway and tracking its eventual return, metering data against a monthly cap, throttling or billing the overage when that cap is crossed, crediting customers when the network goes dark for hours, and unwinding all of the above — equipment, fees, and contract penalties — when a customer disconnects or relocates.

The platform serves four operational constituencies whose work overlaps but never fully coincides. Customers browse serviceability and drive their own account, orders, and appointments. Provisioning agents move orders through their lifecycle, manage the equipment fleet, and execute account-level actions such as plan changes and disconnects. Network operations staff meter usage, log and credit outages, and run the monthly billing close. Dispatchers own the field-scheduling catalog of technicians and install slots. Because several of these actors may act on the same account in quick succession — a disconnect racing a new appointment booking, for instance — the system treats the account as a concurrency anchor and guards the most consequential writes with optimistic version checks. The remainder of this document defines the global contract every endpoint honors (§2), the business rules that govern each workflow (§3), the endpoint surface (§4), and the canonical error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that hold across every endpoint. Where §3 narrates how a particular workflow behaves, §2 fixes the invariants those workflows are built on.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly four roles, spelled precisely as follows: `Customer`, `ProvisioningAgent`, `NetworkOps`, and `Dispatcher`. When a role is well-formed and recognized but is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The four roles partition the work along business lines. A `Customer` is an end subscriber who acts only on the accounts they own — browsing serviceability, creating accounts, orders and transfer requests, booking and cancelling their own appointments, and self-activating a shipped kit. A `ProvisioningAgent` is an operations agent who drives service orders, the equipment lifecycle, account suspend/resume/disconnect/plan-change actions, and transfer approval and completion. A `NetworkOps` operator posts usage, logs/resolves/credits outages, runs the billing close, and manages the reference catalogs. A `Dispatcher` is the field-scheduling role that owns technicians and install slots.

All four roles use an **opaque** identity model: in each case `X-User-ID` is an operator-or-subscriber identifier that the server does not resolve against any persisted entity's `id`. It is never compared to an entity primary key. There is, however, one ownership relationship the server does enforce, and it is keyed on a stored field rather than on entity identity: an `Account` records the subscriber who owns it in `customer_user_id`. When the caller's `X-User-Role` is `Customer`, any action that targets an account, an order, or an appointment belonging to an account is permitted only when that account's `customer_user_id` equals the caller's `X-User-ID`; a `Customer` acting on an account they do not own is rejected with `ERR_NOT_ACCOUNT_OWNER`. The other three roles are not subject to this ownership check.

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

List endpoints return their results through the envelope's `data` array and report pagination state in `meta`. Two query parameters control the window: `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0 and has no upper bound beyond the size of the underlying collection. Requests outside these bounds are treated as invalid input. List endpoints sort their results by `created_at` in ascending order before the window is applied, so paging through `offset` walks the collection from oldest to newest; records sharing an identical `created_at` (which the pinned logical clock makes common) are ordered by their `id` as a stable secondary key. The pagination fields surfaced in `meta` are `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reflects the full size of the filtered collection and `has_more` indicates whether records remain beyond the current window.

### 2.4. Common Resource Properties and Identity

Every persisted resource carries a server-minted `id` formatted as a bare UUID with no type prefix; clients never supply it. Resources also record their creation instant in `created_at` as an ISO 8601 UTC timestamp with three fractional digits.

Most entities additionally carry two mutation-tracking fields: `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that begins at 1 on creation and increments by one each time the resource is mutated. These two fields are present on `Account`, `EquipmentUnit`, `ServiceOrder`, `InstallSlot`, `Technician`, `InstallAppointment`, `BillingCycle`, `OutageEvent`, and `TransferRequest`.

Four entities are deliberately leaner. `ServiceAddress`, `ServicePlan`, `UsageRecord`, and `AccountCredit` are write-light reference or ledger records that carry only `id` and `created_at`: they have neither an `updated_at` nor a `version` field, and nothing in the system mutates them in place after creation. When a workflow below speaks of "bumping a version" or "refreshing the updated timestamp," it never refers to these four.

### 2.5. Serviceability and Speed Governance

A premises is described by a `ServiceAddress`, whose `coverage_status` is one of `SERVICEABLE`, `NOT_SERVICEABLE`, or `PRE_ORDER`, whose `technology` is one of `FIBER`, `CABLE`, `DSL`, or `FIXED_WIRELESS`, and whose `max_serviceable_mbps` records the highest download speed the local plant supports. Two gates run wherever the system commits a plan to an address — when a service order is scheduled or has its self-install kit shipped and when a transfer is approved, both gates run; when an account's plan is changed only the second (speed) gate runs, because the account is already committed to its existing serviceable address. The first gate requires the target address's `coverage_status` to be exactly `SERVICEABLE`; any other coverage status fails this gate with `ERR_ADDRESS_NOT_SERVICEABLE`. The second gate requires the requested plan's `download_mbps` to be at most the address's `max_serviceable_mbps` — equal values pass, and a plan whose download speed exceeds the plant's ceiling by even one megabit per second fails with `ERR_PLAN_EXCEEDS_SERVICEABLE_SPEED`.

### 2.6. Equipment, Billing, and Operational State Dimensions

Several entities track more than one independent dimension of state, and the system never collapses them into one.

An `Account` carries an administrative `status` — one of `PENDING`, `ACTIVE`, `SUSPENDED`, `DISCONNECTED`, or `TRANSFERRED` — that begins at `PENDING` on creation. Independently, it carries an operational `service_state` — one of `PROVISIONING`, `ONLINE`, `THROTTLED`, or `OFFLINE` — that begins at `PROVISIONING` and is derived from the account's active billing cycle and outage situation. The two move on different triggers: administrative actions advance `status`, while metering and outage events drive `service_state`.

A `BillingCycle` likewise carries two orthogonal dimensions on the same row. Its `billing_state` is one of `OPEN`, `CLOSED`, or `FINALIZED` and tracks the accrual lifecycle; its `throttle_state` is one of `UNCAPPED` or `THROTTLED` and tracks the metering dimension. A cycle's `billing_state` evolves only on close and finalize, while its `throttle_state` evolves on usage posts and manual speed restores. The two dimensions never gate each other: a cycle can be `THROTTLED` while still `OPEN`, and closing a cycle does not by itself change its `throttle_state`.

An `EquipmentUnit` runs a cyclic lifecycle through `status` values `IN_INVENTORY`, `LEASED`, `RETURN_PENDING`, `RETURNED`, and `LOST`, beginning at `IN_INVENTORY`. A unit that completes its return and is restocked re-enters inventory and may be leased to a different account, so the same hardware traverses the cycle repeatedly over its service life.

### 2.7. Hierarchical Consistency and Cascade Semantics

Many actions in this system mutate more than one entity. Whenever an operation changes a resource, that resource's `updated_at` is refreshed and — for the version-bearing entities listed in §2.4 — its `version` is incremented by one. This applies to every entity touched in a cascade, not merely the one the caller named. For example, activating a service order touches the order, the equipment unit it assigns, the account, and the new billing cycle; each affected resource records its own mutation. State propagation between parent and child resources is immediate and synchronous: there is no deferred or eventual settlement. The detailed cascades — which entity transitions trigger which downstream transitions and credits — are specified per workflow in §3, and the figures and thresholds those cascades depend on live in §2.8 through §2.11.

### 2.8. Monetary Precision and Time Bases

All monetary amounts in the system are integer cents; there are no fractional cents and no separate currency field. Where a calculation produces a fractional cent before rounding — outage credits, lease prorations, and early-termination fees all divide a fee by a time ratio — the result is rounded half up to the nearest whole cent. The overage tier ladder and the monthly bill total are built entirely from integer-cent inputs and need no rounding step.

Time-based prorations rest on a canonical cycle geometry. When an account is activated, the system opens a billing cycle whose `cycle_start_iso` is the current clock instant and whose `cycle_end_iso` is exactly 30 days later — the canonical 30-day, 43,200-minute cycle that lease and outage prorations measure against. Outage credit proration works in whole minutes between a cycle's `cycle_start_iso` (inclusive) and `cycle_end_iso` (exclusive); lease and early-termination prorations work in whole days and whole months respectively, as detailed in §3.

### 2.9. Nested Resource Retrieval and Referential Existence

The entity topology here is flat: resources reference one another through foreign-key fields rather than through deeply nested URLs, and action endpoints address a single resource by its `id` in the path. For any request, every referenced resource identifier must resolve to an existing record. Path identifiers are validated left to right first, and then the foreign keys named in the request body are validated; the first identifier that does not resolve causes the request to fail with `ERR_NOT_FOUND`. This existence check runs after authentication and authorization but before any business-rule evaluation, so a request that names a nonexistent account never reaches the state or constraint checks that would otherwise apply.

### 2.10. Uniqueness Constraints

Two reference catalogs enforce uniqueness on a human-meaningful key. An `EquipmentUnit` carries a hardware `serial` that must be unique across all equipment units; creating a unit whose serial already exists is rejected with `ERR_DUPLICATE_SERIAL`. A `ServicePlan` carries a `code` that must be unique across all plans; creating a plan whose code is already in use is rejected with `ERR_DUPLICATE_PLAN_CODE`.

### 2.11. Optimistic Concurrency Control

Four account-mutating operations are guarded by optimistic concurrency control anchored on the `version` of the target `Account`. Each such request must include an `expected_account_version` field carrying the client's last observed account `version`. The server compares that value against the account's current `version`; if they match, the operation proceeds and increments the account's `version` by one, and if they differ the operation is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). A mismatch means another writer has advanced the account since the client last read it — the client's view is stale, and the write is refused rather than allowed to clobber a state it never saw.

The four guarded operations are: booking an install appointment, changing an account's plan, disconnecting an account, and completing a transfer. The first — booking an install appointment — takes `expected_account_version` because the account may have been disconnected or transferred out from under the booking client, legitimately superseding the provisioning intent. The second — changing an account's plan — takes it because another writer may have just changed the plan or disconnected the account. The third and fourth — disconnect and transfer completion — take it because both are terminal account transitions that must not race a concurrent change. No other endpoint accepts or requires `expected_account_version`; endpoints not in this set neither take the field nor perform a version check.

## 3. Business Logic & Workflows

### 3.1. Reference Catalogs: Addresses, Plans, Technicians, and Equipment

Before any subscriber can be provisioned, the operator populates four reference catalogs. A `ServiceAddress` is created with its `line1` street line, its `postal_code`, its `coverage_status`, its `technology`, its `max_serviceable_mbps`, and its `self_install_eligible` flag indicating whether self-install kits are permitted at that premises. A serviceability lookup against an address returns exactly these serviceability attributes — coverage, technology, the speed ceiling, and self-install eligibility — so a prospective subscriber can learn whether and how fast they can be served.

A `ServicePlan` is defined by its unique `code`, its `tier` (one of `BASIC`, `PLUS`, `GIG`, or `MULTI_GIG`), its provisioned `download_mbps`, the reduced `throttled_mbps` that applies once a throttle takes effect, its recurring `monthly_fee_cents`, its `included_gb` data cap, its `overage_policy` (one of `BILL`, `THROTTLE`, or `UNLIMITED`), its `contract_term_months` (where 0 denotes a month-to-month plan with no early-termination fee), and its `etf_full_cents`, the early-termination fee in force at the very start of the term that decays to zero by term end.

A `Technician` is created with a `name` and carries a `travel_buffer_minutes` value — defaulting to 30 minutes when not supplied — that reserves travel time after each appointment before the technician is considered free again, and an `active` flag, defaulting to true, indicating whether the technician may be assigned new appointments. Dispatchers also create install slots, described in §3.4.

Equipment is stocked one unit at a time. An `EquipmentUnit` is created with its `kind` (one of `MODEM`, `ROUTER`, or `GATEWAY`), its unique `serial`, and its `lease_fee_cents_per_cycle`, the monthly lease fee charged while the unit is leased. A freshly created unit begins life `IN_INVENTORY` with no `account_id` set; its `leased_at_iso` — the instant the current lease began, which anchors lease proration — is populated only when the unit is later leased. The equipment fleet can be listed and filtered by `account_id` and by `status`.

### 3.2. Account Creation and Activation

A subscriber relationship is anchored by an `Account`, created with the `service_address_id` of the premises it serves, the `plan_id` of the plan it will provision, and the `customer_user_id` of the owning subscriber. When the caller is a `Customer`, the supplied `customer_user_id` must equal the caller's `X-User-ID`; a `Customer` creating an account they would not own is rejected with `ERR_NOT_ACCOUNT_OWNER`. A new account is born in `PENDING` administrative `status` with `service_state` of `PROVISIONING` and `version` 1; its `contract_start_iso`, `credit_balance_cents`, and `equipment_unit_id` are not yet meaningful (the credit balance reads as 0 and there is no leased unit). Accounts can be listed and filtered by `service_address_id`, `plan_id`, `equipment_unit_id`, and `status`.

Provisioning an account is the work of a `ServiceOrder`, created against an `account_id` with an `order_type` (one of `NEW_INSTALL`, `TRANSFER_IN`, or `UPGRADE`), an `install_mode` (one of `TECH_INSTALL` or `SELF_INSTALL`), and a `requested_plan_id` naming the plan the order will provision. An order opens in `DRAFT`. Its `equipment_unit_id` stays empty until activation, when a unit is assigned. Orders can be retrieved individually and listed with filters on `account_id`, `requested_plan_id`, `equipment_unit_id`, and `status`.

From `DRAFT` the order forks along its install mode. A `TECH_INSTALL` order advances to `SCHEDULED` the moment an install appointment is booked for it (see §3.4); booking is permitted only when the order's install mode is `TECH_INSTALL`, the account's service address has `coverage_status` of `SERVICEABLE`, and the requested plan's `download_mbps` does not exceed the address's `max_serviceable_mbps`. A `SELF_INSTALL` order instead advances from `DRAFT` to `KIT_SHIPPED` when its kit is shipped; shipping a kit requires the order's install mode to be `SELF_INSTALL`, the address `coverage_status` to be `SERVICEABLE`, the requested plan's `download_mbps` to not exceed the address's `max_serviceable_mbps` (the §2.5 speed gate, checked after serviceability and before eligibility), and the address to be flagged `self_install_eligible`. Requesting a kit when the address is not self-install eligible is rejected with `ERR_SELF_INSTALL_NOT_ELIGIBLE`. Shipping does not assign or hold any specific equipment unit: the order's `equipment_unit_id` stays empty and no unit changes state, so the kit ships even when no `IN_INVENTORY` unit exists; the actual unit is selected and leased only at activation.

The two branches rejoin at activation. Activating a `SCHEDULED` order requires the order's install appointment to have reached `COMPLETED`; activating a `KIT_SHIPPED` order has no appointment precondition (the subscriber may self-activate). Either way, activation is the join point: the system selects an `EquipmentUnit` that is `IN_INVENTORY` — the oldest such unit by `created_at` when more than one is available — assigns it to the order by setting the order's `equipment_unit_id`, transitions that unit from `IN_INVENTORY` to `LEASED` while stamping its `leased_at_iso` to the current instant, and sets the account's `equipment_unit_id` to point at the now-leased unit. If no `IN_INVENTORY` unit is available to assign, activation fails with `ERR_NO_EQUIPMENT_AVAILABLE`. Activation also drives the account from `PENDING` to `ACTIVE`: the account's `contract_start_iso` is stamped to the current clock instant (this is the basis for early-termination decay), its `service_state` becomes `ONLINE`, and a fresh `OPEN` billing cycle is created with `cycle_start_iso` at the current instant and `cycle_end_iso` exactly 30 days later. The order itself lands in `ACTIVATED`, a terminal order state.

An order may be cancelled from `DRAFT`, `SCHEDULED`, or `KIT_SHIPPED`, reaching the terminal `CANCELLED`. Cancelling a `DRAFT` order has no side effects. Cancelling a `SCHEDULED` order cascades to its booked appointment: that appointment moves to `CANCELLED`, the appointment's slot decrements its `booked_count` by one, and a slot that had been `FULL` returns to `OPEN`. Cancelling a `KIT_SHIPPED` order has no equipment side effect, since shipping never reserved a unit; the order simply moves to `CANCELLED`.

### 3.3. Plan Changes, Suspension, and Resumption

Once an account is `ACTIVE`, a `ProvisioningAgent` may change its provisioned plan. A plan change names the `new_plan_id` to switch to and carries `expected_account_version` for the concurrency guard described in §2.11; on success the account's `plan_id` is updated and its `version` increments by one. Because a plan change commits a new plan to the account's existing address, it runs the speed gate of §2.5: if the new plan's download speed exceeds the address's serviceable ceiling the change is rejected with `ERR_PLAN_EXCEEDS_SERVICEABLE_SPEED`.

Service can be paused and resumed without disconnecting. Suspending an `ACTIVE` account moves its `status` to `SUSPENDED` and sets `service_state` to `OFFLINE`. Resuming a `SUSPENDED` account returns `status` to `ACTIVE`; its `service_state` becomes `ONLINE`, unless the account's open billing cycle currently sits in `THROTTLED` throttle state, in which case the resumed operational state is `THROTTLED` instead. Both actions are agent-driven and require the account to be in the appropriate originating administrative state.

### 3.4. Field Scheduling: Slots, Appointments, and Capacity

A `Dispatcher` publishes availability as `InstallSlot` records. A slot is created for a `technician_id`, with a half-open window running from `window_start_iso` (inclusive) to `window_end_iso` (exclusive), and a `capacity` giving the maximum number of appointments bookable in that window. A new slot opens with `booked_count` of 0 and `status` of `OPEN`; its `booked_count` tracks the number of non-cancelled appointments referencing it, and its `status` becomes `FULL` precisely when `booked_count` equals `capacity`, returning to `OPEN` whenever a booking is released and the count falls back below capacity. Slots can be listed and filtered by `technician_id` and `status`.

Booking an `InstallAppointment` ties a `TECH_INSTALL` order to a slot. The booking request carries the `service_order_id` of the order being fulfilled, the `install_slot_id` of the slot to book, the appointment's `start_iso` and `end_iso`, and `expected_account_version`. The appointment's `technician_id` is copied from the chosen slot rather than supplied by the caller, and the appointment opens in `BOOKED`. A successful booking increments the slot's `booked_count` by one (tipping the slot to `FULL` if that reaches capacity), advances the order from `DRAFT` to `SCHEDULED`, and — because booking is one of the four OCC-guarded account writes of §2.11 — increments the account's `version` by one.

Booking is subject to a layered set of checks beyond the serviceability and speed gates of §3.2. The slot must have room: if its `booked_count` has already reached `capacity` the booking is rejected with `ERR_SLOT_AT_CAPACITY`. The technician must be free across the appointment plus their travel buffer: the half-open interval from the appointment's `start_iso` through its `end_iso` extended by the technician's `travel_buffer_minutes` must not intersect any other `BOOKED` or `COMPLETED` appointment of the same technician, and an intersection is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`. The appointment must fit its slot: the half-open interval from `start_iso` to `end_iso` must fall entirely within the slot's window from `window_start_iso` to `window_end_iso`, and an appointment that spills outside the slot window is rejected with `ERR_APPOINTMENT_OUTSIDE_SLOT` (HTTP 422).

A booked appointment can resolve three ways. Completing it moves `BOOKED` to `COMPLETED`, which is what unblocks activation of the associated `SCHEDULED` order. Marking it a no-show moves `BOOKED` to `NO_SHOW`, decrements the slot's `booked_count` by one, and returns a `FULL` slot to `OPEN`. Cancelling it moves `BOOKED` to `CANCELLED`, likewise decrementing the slot's `booked_count` and returning a `FULL` slot to `OPEN`; a `Customer` may cancel their own appointment, as may a `ProvisioningAgent`. Appointments can be retrieved and listed with filters on `service_order_id`, `install_slot_id`, and `technician_id`.

### 3.5. Metering Usage, Data Caps, and Throttling

Usage is recorded against an open cycle as `UsageRecord` entries. A usage record carries the `account_id` whose consumption it posts, the `billing_cycle_id` of the cycle it posts to, a `posted_at_iso` timestamp marking when the data was metered, and a `gb` count of gigabytes consumed, which must be greater than zero. The `posted_at_iso` must fall within the target cycle's window; a record metered outside the window from `cycle_start_iso` to `cycle_end_iso` is rejected with `ERR_USAGE_OUTSIDE_CYCLE` (HTTP 422). Posting a record adds its `gb` to the cycle's running `usage_gb`. Usage records can be listed and filtered by `account_id` and `billing_cycle_id`.

The data cap governs what happens as consumption climbs. The cap is the plan's `included_gb`; usage exactly equal to the cap is not yet over, and only cumulative usage strictly greater than `included_gb` counts as overage. Where the account's plan has an `overage_policy` of `THROTTLE`, the first usage post that pushes the cycle's cumulative `usage_gb` strictly above `included_gb` — while the cycle is still `OPEN` — flips the cycle's `throttle_state` from `UNCAPPED` to `THROTTLED`, and if the account is `ACTIVE` its `service_state` moves from `ONLINE` to `THROTTLED` in the same step. Throttling is a metering action only: it never changes the cycle's `billing_state`, and the plan's `throttled_mbps` is the speed the subscriber is held to while throttled.

A throttle can be lifted manually — for instance after a paid top-up. Restoring speed on an account sets its open cycle's `throttle_state` from `THROTTLED` back to `UNCAPPED`, and if the account is `ACTIVE` its `service_state` moves from `THROTTLED` back to `ONLINE`. Restore-speed requires the account to have an `OPEN` billing cycle that currently sits in `THROTTLED` throttle state; if there is no open cycle or the open cycle is not `THROTTLED`, the request is rejected with `ERR_INVALID_STATE`. This is a one-time manual restore that leaves the cycle's `billing_state` untouched, and on success the operation returns the updated billing-cycle object in `data`.

### 3.6. Outages and SLA Credits

Network operations log an `OutageEvent` against an affected `account_id` and the `billing_cycle_id` of the cycle the outage falls within, recording the `started_at_iso` at which service went dark. An outage opens in `OPEN` with no `ended_at_iso` and a `duration_minutes` of 0. The `started_at_iso` must lie within the named cycle's window; an outage logged outside the window is rejected with `ERR_OUTAGE_OUTSIDE_CYCLE` (HTTP 422). Outages can be listed and filtered by `account_id` and `billing_cycle_id`.

Resolving an outage closes the interval. The resolve request supplies the `ended_at_iso`, which must be strictly after the `started_at_iso`; the system then sets `ended_at_iso` and computes `duration_minutes` as the whole number of minutes between start and end, moving the outage from `OPEN` to `RESOLVED`. A resolved outage that qualifies under the service-level agreement can be credited, and one that does not can be dismissed. The SLA qualifying threshold is 240 minutes (four hours): issuing a credit requires the outage to be `RESOLVED` with `duration_minutes` of at least 240, and an attempt to credit an outage whose duration is below that threshold is rejected with `ERR_OUTAGE_BELOW_SLA`. Dismissing a `RESOLVED` outage moves it to `DISMISSED` with no further effect and is the path used for sub-threshold or otherwise non-qualifying outages.

Issuing a credit moves the outage from `RESOLVED` to `CREDITED` and emits an `AccountCredit`. The credit amount is the outage proration of one month's fee. Specifically, the system computes the cycle length as the whole minutes between the billing cycle's `cycle_start_iso` (inclusive) and `cycle_end_iso` (exclusive), then sums the qualifying outage minutes for this account in this cycle — drawing from every outage of the account whose `billing_cycle_id` is this cycle, whose status is either `RESOLVED` or `CREDITED`, and whose `duration_minutes` is at least 240. Overlapping outage intervals are merged before summing, so a minute covered by two outages at once counts only once toward the qualifying total. The credit is the plan's `monthly_fee_cents` multiplied by the qualifying minutes divided by the cycle minutes, rounded half up to whole cents, and then capped so it never exceeds one month's `monthly_fee_cents`. The emitted credit carries `source_type` of `OUTAGE` and a `source_id` pointing at the originating outage event, and the account's `credit_balance_cents` is recomputed to reflect it. The issue-credit operation returns `200 OK` with the now-`CREDITED` outage event object in `data` (not the emitted credit).

### 3.7. Equipment Return, Restock, and Loss

When an account is disconnected or transferred (see §3.8), its leased unit does not vanish from the books; it begins a return journey. The leased `EquipmentUnit` moves from `LEASED` to `RETURN_PENDING`, and that very transition emits a lease-proration credit for the unused-days portion of the final cycle. The proration works in whole days: the cycle length is the whole days in the open billing cycle window, the days used are the whole days from the cycle's `cycle_start_iso` up to the current clock instant counting the start day, and the days remaining is the cycle length minus the days used but never below zero. The refund is the unit's `lease_fee_cents_per_cycle` multiplied by the days remaining divided by the cycle days, rounded half up to whole cents. This emits an `AccountCredit` with `source_type` of `LEASE_PRORATE` and a `source_id` naming the unit.

From `RETURN_PENDING` the unit resolves one of two ways. Confirming the return moves it to `RETURNED` and clears its `account_id`; the lease-proration credit stands. A returned unit is not yet re-leasable — it becomes assignable again only after an explicit restock moves it from `RETURNED` back to `IN_INVENTORY`, closing the cycle so the same hardware can be leased to a new account. Alternatively, a unit in `RETURN_PENDING` can be marked lost, moving it to the terminal `LOST` state. Because a lost unit was never actually returned, the lease-proration refund must not stand: marking the unit lost reverses the previously emitted `LEASE_PRORATE` credit, negating its amount so the net lease credit for that unit is zero. This preserves the lease conserved quantity — the operator never refunds lease days on hardware it never got back.

### 3.8. Disconnection and the Final Cycle

Disconnecting an account is the most far-reaching single action in the system, and it is OCC-guarded: the request carries `expected_account_version`, which must match the account's current `version` per §2.11. An account may be disconnected from either `ACTIVE` or `SUSPENDED`; either way the account moves to the terminal `DISCONNECTED` status and its `service_state` becomes `OFFLINE`. The disconnect then fans out into a fixed cascade. First, the system computes the early-termination fee on the account's currently-provisioned plan and adds it as a charge on the open billing cycle. Second, the account's leased equipment unit moves from `LEASED` to `RETURN_PENDING`, which (per §3.7) emits the lease-proration credit. Third, the open billing cycle is closed and then finalized, so its `total_due_cents` is recomputed to include the early-termination fee, any overage, the lease proration, and all applicable credits. Finally, the account's `version` increments by one.

The early-termination fee decays linearly across the contract term. For a month-to-month plan — one whose `contract_term_months` is 0 — the fee is always zero. Otherwise the system counts the whole months elapsed between the account's `contract_start_iso` and the current clock instant, computes the months remaining as the plan's `contract_term_months` minus those elapsed months but never below zero, and sets the fee to the plan's `etf_full_cents` multiplied by the months remaining divided by `contract_term_months`, rounded half up to whole cents. At or past term end, where no months remain, the fee is zero. On a plain disconnect this fee is added as a charge on the final cycle.

### 3.9. Transfers and the ETF Waiver

A relocation is handled as a `TransferRequest`, created against an `account_id` with the `to_service_address_id` of the destination premises, the `to_plan_id` of the plan at the destination (which may equal the current plan), and a `waive_etf` flag — defaulting to true — declaring whether the move waives the source account's early-termination fee. A transfer request opens in `REQUESTED`. Transfer requests can be retrieved and listed with filters on `account_id`, `to_service_address_id`, `to_plan_id`, and `status`.

A request advances through approval and completion or is rejected. Approving a `REQUESTED` transfer moves it to `APPROVED` and runs the serviceability and speed gates of §2.5 against the destination: the `to_service_address_id` must have `coverage_status` of `SERVICEABLE` (else `ERR_ADDRESS_NOT_SERVICEABLE`) and the `to_plan_id`'s download speed must not exceed the destination address's `max_serviceable_mbps` (else `ERR_PLAN_EXCEEDS_SERVICEABLE_SPEED`). Rejecting a `REQUESTED` transfer moves it to the terminal `REJECTED` with no effect.

Completing an `APPROVED` transfer is the terminal, OCC-guarded step: the request carries `expected_account_version`, the request must be in `APPROVED`, and the account must be `ACTIVE` (an account that is not `ACTIVE` is rejected with `ERR_ACCOUNT_NOT_ACTIVE`). Completion moves the transfer to `COMPLETED` and increments the account's `version` by one. It cascades into the account exactly as a disconnect does, with one deliberate difference governed by the waiver. The account moves from `ACTIVE` to the terminal `TRANSFERRED` and its `service_state` becomes `OFFLINE`; its leased equipment unit moves from `LEASED` to `RETURN_PENDING` (emitting the lease-proration credit); and its open billing cycle is closed and then finalized. The difference is the early-termination treatment: when `waive_etf` is true, no early-termination charge is added to the cycle, and instead the system emits an `AccountCredit` with `source_type` of `TRANSFER_WAIVER` whose amount equals the early-termination fee that would otherwise have applied. The waiver is the compensating counterpart of a disconnect's fee — it leaves the net early-termination burden at exactly zero.

### 3.10. The Billing Close and Final Settlement

A cycle's accrual lifecycle is run by `NetworkOps`. Billing cycles are normally born from activation, but one can also be opened explicitly for an `account_id` by supplying its `cycle_start_iso` and `cycle_end_iso`; such a cycle opens with `billing_state` of `OPEN` and `throttle_state` of `UNCAPPED`, and no validation forbids an account from holding more than one `OPEN` cycle at once. Wherever a workflow speaks of "the open cycle" for an account (the throttle trigger and restore, the resume service-state decision, and the disconnect/transfer final-cycle cascade), it resolves to the most-recently-created `OPEN` cycle of that account. Cycles can be retrieved and listed with filters on `account_id` and `billing_state`.

Closing a cycle moves its `billing_state` from `OPEN` to `CLOSED`, but only when none of the cycle's outage events is still `OPEN` — every outage on the cycle must be `RESOLVED`, `CREDITED`, or `DISMISSED` first, or the close is rejected with `ERR_CYCLE_HAS_OPEN_OUTAGE`. Closing freezes the cycle's `usage_gb` to the sum of the `gb` across every usage record whose `posted_at_iso` falls within the cycle window, runs the final overage computation to set `overage_charge_cents`, and sets the cycle's `throttle_state` according to whether the data cap was crossed.

The final overage charge runs a three-tier ladder, but only when the plan's `overage_policy` is `BILL` — a plan whose policy is `THROTTLE` or `UNLIMITED` never bills overage, so its overage charge is zero. The billable overage is the cumulative usage minus the plan's `included_gb`, never below zero (usage exactly at the cap is not over). That overage is priced through three tiers: the first 50 gigabytes of overage cost 50 cents per gigabyte, the next 50 gigabytes cost 30 cents per gigabyte, and every gigabyte of overage beyond the first 100 costs 20 cents per gigabyte. The tier costs are summed, and then the total overage charge is capped so it never exceeds 6,000 cents. At close, the cumulative usage fed into this ladder is the frozen `usage_gb` — the actual chronological sum of posted records.

The same ladder also backs a forward-looking estimate available mid-cycle as a computed read. The overage estimate accepts an optional `as_of_iso` marking the as-of date — defaulting to the current clock instant when omitted — and projects usage to cycle end: the usage so far is the sum of `gb` across this cycle's usage records whose `posted_at_iso` lies within the cycle window and at or before the as-of instant, the days elapsed are the whole days from `cycle_start_iso` to the as-of instant counting the start day (the same day count §3.7 uses), and it takes that usage so far divided by the days elapsed, multiplies by the number of cycle days, takes the floor of that projection, and then runs the identical three-tier ladder and 6,000-cent cap on the projected figure. The estimate is a pure non-mutating read: it persists nothing and leaves the cycle in `OPEN`, returning the billing-cycle object with its `overage_charge_cents` field carrying the projected estimate (the stored cycle and its other fields are left untouched). The estimate and the final figure agree only when the back half of the cycle follows the linear projection; they diverge whenever later usage departs from that straight-line pace.

Finalizing a `CLOSED` cycle moves its `billing_state` to `FINALIZED` and computes the cycle's `total_due_cents`; finalize called on a cycle that is not `CLOSED` is rejected with `ERR_CYCLE_NOT_CLOSED`. The total is assembled in a pinned order so the promotional discount, which keys off an intermediate subtotal, is well defined. Begin with the plan fee, the plan's `monthly_fee_cents`. Add the lease fee: the `lease_fee_cents_per_cycle` of the account's currently-leased unit when one is held, or zero when none is, except that on a disconnect or transfer cycle the lease fee is the days-used charge — the full cycle lease fee reduced by the lease-proration credit. Add the final overage charge from the ladder above, which is zero unless the plan's policy is `BILL`. Add the early-termination fee, which is non-zero only on a disconnect cycle. Now form the pre-discount subtotal as the plan fee plus the lease fee — and only those two. The promotional discount is then keyed strictly on that subtotal: a subtotal of at least 10,000 cents earns a 1,000-cent discount; otherwise a subtotal of at least 8,000 cents earns a 500-cent discount; otherwise there is no discount. Separately, the applied credits are the sum of the `amount_cents` of every un-applied `AccountCredit` for the account. The final `total_due_cents` is the plan fee plus the lease fee plus the overage plus the early-termination fee, minus the applied credits, minus the promotional discount. This total may go negative — a credit-heavy cycle is carried as a credit balance rather than floored at zero. Finalizing also marks every `AccountCredit` it consumed as `applied` true, so those credits are not double-counted against a later cycle.

### 3.11. Account Credits and the Goodwill Path

Credits accrue to an account from several sources and pool into a single balance. Every `AccountCredit` carries the `account_id` it benefits, a `source_type` describing its origin, a `source_id` naming the originating record, an `amount_cents` greater than zero, and an `applied` flag — initially false — that turns true once a finalized cycle has consumed it. The `source_type` spans four origins: `OUTAGE` for SLA outage credits (§3.6), `LEASE_PRORATE` for unused-lease refunds (§3.7), `TRANSFER_WAIVER` for waived early-termination fees (§3.9), and `GOODWILL` for manually issued credits. A goodwill credit is issued directly to an account by supplying only the `amount_cents`; the system stamps its `source_type` to `GOODWILL`, leaves its `source_id` null (a goodwill credit has no originating record), and recomputes the account's `credit_balance_cents`. Because this creates a new `AccountCredit` resource, the issue endpoint returns `201 Created` with the newly created credit object in `data`. The account's `credit_balance_cents` is always the sum of the `amount_cents` of that account's un-applied credits. Individual credits can be retrieved, and credits can be listed and filtered by `account_id` and by `applied`.

### 3.12. Validation Ordering and the Test Clock

When several checks could fire on one request, they are evaluated in a fixed priority order so the failure a caller sees is deterministic. Authentication comes first: a missing or malformed `X-User-ID` or `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` before anything else is examined. Authorization is second: a recognized role not permitted for the endpoint yields `ERR_FORBIDDEN_FOR_ROLE`. Existence is third: any referenced resource id that does not resolve yields `ERR_NOT_FOUND`, with path identifiers checked left to right before body foreign keys. Request well-formedness is fourth: a malformed body, a missing required field, or a non-positive `gb`, `amount_cents`, or `capacity`, or an interval whose end is not after its start, yields `ERR_INVALID_REQUEST`. State legality is fifth: a target resource not in a state permitting the requested transition yields `ERR_INVALID_STATE`. Account ownership is sixth: a `Customer` acting on an account they do not own yields `ERR_NOT_ACCOUNT_OWNER`. The domain-specific business checks follow in their own order — serviceability before speed, then self-install eligibility, then slot capacity, then technician double-booking, then the appointment-within-slot check, and so on through the outage, cycle, equipment, and concurrency checks described in their workflows above. The optimistic-concurrency check on `expected_account_version`, when it applies, is evaluated within this domain band: a stale version yields `ERR_STALE_ACCOUNT_VERSION`.

The system runs against a controllable logical clock so time-dependent behavior — cycle windows, proration day and month counts, contract decay — is reproducible. An administrative capability pins the server clock to a supplied UTC instant given as `to_iso8601`; once set, every field stamped with "the current instant" (a cycle's start, an account's `contract_start_iso`, a unit's `leased_at_iso`, and the now-anchored proration math) reads from this pinned clock, as do the `created_at` and `updated_at` timestamps stamped on every persisted resource. The lone exception is the response envelope's `api_request_timestamp` (§2.2), which is always real server wall-clock time and ignores the pinned clock. The `/_clock/set_current_utc` endpoint returns `200 OK` with an empty object in `data`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code; operations that modify or transition an existing resource, including the action endpoints that drive state machines, return a `200 OK` status code. Every request must carry the `X-User-ID` and `X-User-Role` headers described in §2.1. The request and response bodies for each endpoint are not restated here — they are specified by the workflow narratives in §3 — and this table is intentionally limited to the routing contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/service-addresses` | Create a service address (serviceability record) | ProvisioningAgent, NetworkOps |
| GET | `/service-addresses/{id}` | Get a service address | Customer, ProvisioningAgent, NetworkOps, Dispatcher |
| GET | `/service-addresses/{id}/serviceability` | Serviceability check for an address | Customer, ProvisioningAgent, NetworkOps, Dispatcher |
| POST | `/service-plans` | Create a service plan | ProvisioningAgent, NetworkOps |
| GET | `/service-plans/{id}` | Get a service plan | Customer, ProvisioningAgent, NetworkOps, Dispatcher |
| POST | `/technicians` | Create a technician | Dispatcher |
| GET | `/technicians/{id}` | Get a technician | Dispatcher, ProvisioningAgent, NetworkOps |
| POST | `/equipment-units` | Create an equipment unit in inventory | ProvisioningAgent, NetworkOps |
| GET | `/equipment-units/{id}` | Get an equipment unit | Customer, ProvisioningAgent, NetworkOps |
| GET | `/equipment-units` | List equipment units | Customer, ProvisioningAgent, NetworkOps |
| POST | `/equipment-units/{id}/confirm-return` | Confirm a returned unit | ProvisioningAgent |
| POST | `/equipment-units/{id}/restock` | Restock a returned unit into inventory | ProvisioningAgent |
| POST | `/equipment-units/{id}/mark-lost` | Mark a unit lost | ProvisioningAgent |
| POST | `/accounts` | Create an account | Customer, ProvisioningAgent |
| GET | `/accounts/{id}` | Get an account | Customer, ProvisioningAgent, NetworkOps, Dispatcher |
| GET | `/accounts` | List accounts | ProvisioningAgent, NetworkOps, Dispatcher |
| POST | `/accounts/{id}/change-plan` | Change the account's provisioned plan | ProvisioningAgent |
| POST | `/accounts/{id}/suspend` | Suspend service | ProvisioningAgent |
| POST | `/accounts/{id}/resume` | Resume service | ProvisioningAgent |
| POST | `/accounts/{id}/restore-speed` | Lift the throttle on the open cycle | ProvisioningAgent |
| POST | `/accounts/{id}/disconnect` | Disconnect the account | ProvisioningAgent |
| POST | `/accounts/{id}/credits` | Issue a manual goodwill credit | ProvisioningAgent, NetworkOps |
| POST | `/service-orders` | Create a service order | Customer, ProvisioningAgent |
| GET | `/service-orders/{id}` | Get a service order | Customer, ProvisioningAgent, NetworkOps, Dispatcher |
| GET | `/service-orders` | List service orders | Customer, ProvisioningAgent, NetworkOps, Dispatcher |
| POST | `/service-orders/{id}/ship-kit` | Ship a self-install kit | ProvisioningAgent |
| POST | `/service-orders/{id}/activate` | Activate the order (assign equipment, activate account) | Customer, ProvisioningAgent |
| POST | `/service-orders/{id}/cancel` | Cancel the order | ProvisioningAgent |
| POST | `/install-slots` | Create an install slot | Dispatcher |
| GET | `/install-slots/{id}` | Get an install slot | Customer, ProvisioningAgent, NetworkOps, Dispatcher |
| GET | `/install-slots` | List install slots | Customer, ProvisioningAgent, NetworkOps, Dispatcher |
| POST | `/install-appointments` | Book an install appointment | Customer, ProvisioningAgent |
| GET | `/install-appointments/{id}` | Get an install appointment | Customer, ProvisioningAgent, NetworkOps, Dispatcher |
| GET | `/install-appointments` | List install appointments | Customer, ProvisioningAgent, NetworkOps, Dispatcher |
| POST | `/install-appointments/{id}/complete` | Mark an appointment completed | ProvisioningAgent |
| POST | `/install-appointments/{id}/no-show` | Mark an appointment no-show | ProvisioningAgent |
| POST | `/install-appointments/{id}/cancel` | Cancel an appointment | Customer, ProvisioningAgent |
| POST | `/billing-cycles` | Open a billing cycle for an account | NetworkOps, ProvisioningAgent |
| GET | `/billing-cycles/{id}` | Get a billing cycle | Customer, ProvisioningAgent, NetworkOps |
| GET | `/billing-cycles` | List billing cycles | Customer, ProvisioningAgent, NetworkOps |
| GET | `/billing-cycles/{id}/overage-estimate` | Forward-looking overage estimate | Customer, ProvisioningAgent, NetworkOps |
| POST | `/billing-cycles/{id}/close` | Close a cycle (freeze usage, final overage) | NetworkOps |
| POST | `/billing-cycles/{id}/finalize` | Finalize a cycle (compute total, apply credits) | NetworkOps |
| POST | `/usage-records` | Post a usage record to a cycle | NetworkOps |
| GET | `/usage-records/{id}` | Get a usage record | Customer, ProvisioningAgent, NetworkOps |
| GET | `/usage-records` | List usage records | Customer, ProvisioningAgent, NetworkOps |
| POST | `/outage-events` | Log an outage event | NetworkOps |
| GET | `/outage-events/{id}` | Get an outage event | Customer, ProvisioningAgent, NetworkOps |
| GET | `/outage-events` | List outage events | Customer, ProvisioningAgent, NetworkOps |
| POST | `/outage-events/{id}/resolve` | Resolve an outage | NetworkOps |
| POST | `/outage-events/{id}/issue-credit` | Issue an outage credit | NetworkOps |
| POST | `/outage-events/{id}/dismiss` | Dismiss a resolved outage | NetworkOps |
| GET | `/account-credits/{id}` | Get an account credit | Customer, ProvisioningAgent, NetworkOps |
| GET | `/account-credits` | List account credits | Customer, ProvisioningAgent, NetworkOps |
| POST | `/transfer-requests` | Create a transfer request | Customer, ProvisioningAgent |
| GET | `/transfer-requests/{id}` | Get a transfer request | Customer, ProvisioningAgent, NetworkOps |
| GET | `/transfer-requests` | List transfer requests | Customer, ProvisioningAgent, NetworkOps |
| POST | `/transfer-requests/{id}/approve` | Approve a transfer | ProvisioningAgent |
| POST | `/transfer-requests/{id}/complete` | Complete a transfer | ProvisioningAgent |
| POST | `/transfer-requests/{id}/reject` | Reject a transfer | ProvisioningAgent |
| POST | `/_clock/set_current_utc` | Set the server clock to a fixed UTC instant (test-driving) | NetworkOps, ProvisioningAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_NOT_ACCOUNT_OWNER` | 403 Forbidden |
| `ERR_ADDRESS_NOT_SERVICEABLE` | 409 Conflict |
| `ERR_PLAN_EXCEEDS_SERVICEABLE_SPEED` | 409 Conflict |
| `ERR_SELF_INSTALL_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_SLOT_AT_CAPACITY` | 409 Conflict |
| `ERR_TECHNICIAN_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_APPOINTMENT_OUTSIDE_SLOT` | 422 Unprocessable Entity |
| `ERR_OUTAGE_BELOW_SLA` | 409 Conflict |
| `ERR_CYCLE_HAS_OPEN_OUTAGE` | 409 Conflict |
| `ERR_NO_EQUIPMENT_AVAILABLE` | 409 Conflict |
| `ERR_STALE_ACCOUNT_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_DUPLICATE_PLAN_CODE` | 409 Conflict |
| `ERR_USAGE_OUTSIDE_CYCLE` | 422 Unprocessable Entity |
| `ERR_OUTAGE_OUTSIDE_CYCLE` | 422 Unprocessable Entity |
| `ERR_CYCLE_NOT_CLOSED` | 409 Conflict |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
