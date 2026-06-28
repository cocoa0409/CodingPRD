# Pet Cremation & Aftercare API — Product Requirements Document

## 1. Introduction

When a companion animal dies, the practical work of dignified aftercare spans two worlds that rarely talk to one another: the veterinary clinic (or the grieving household) on one side, and the crematory floor with its coolers, retorts, and scheduling on the other. This API exists to bridge those worlds into a single, auditable workflow. It tracks a deceased pet from the moment of intake — whether the body is collected at a clinic or at a family's home — through transport, refrigerated holding, staging into a cremation batch, the firing itself, certificate issuance, and finally the return of ashes to a private owner or the communal disposition of pooled remains.

The system's defining obligation is an unbroken **chain of custody**: every physical hop the body takes is recorded as an immutable event, and no downstream step may proceed unless the chain that precedes it is continuous. Layered on top of custody is an independent **billing lifecycle** that recognizes revenue, allocates pooled firing costs by weight, applies handling fees, and keeps each clinic's running account balance within its credit limit. Because crematory capacity is finite — coolers have slots, retorts have weight ceilings and non-overlapping firing windows, viewing rooms have schedules — the API also acts as a scheduler and quota allocator, refusing actions that would double-book a resource or exceed a physical limit.

This document specifies the complete contract: the resource model, the parallel state machines that govern custody and billing, the calculation rules for pricing and balances, the validation precedence that decides which error a rejected request receives, and the role-based access boundaries that separate clinic staff, pet owners, and crematory personnel.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across every endpoint. Domain workflows and the business rules embedded within them are detailed in Section 3.

### 2.1. User and Role-Based Access Control

Every request must be authenticated with two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing, or `X-User-Role` does not name a recognized role, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly four roles: `CrematoryAdmin`, `CrematoryOperator`, `ClinicStaff`, and `PetOwner`. When a request is authenticated but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four roles fall into two identity families. `CrematoryAdmin` is the crematory back-office principal who manages clinics, coolers, retorts, billing (invoice issuance, voiding, and payment), batch reconciliation, and the logical clock. `CrematoryOperator` is the crematory floor principal who drives the physical chain of custody — transport, receiving, cooler storage, staging, firing, completion, and return — along with keepsake and memorial production. For both of these crematory roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it (for example, as the `custodian` recorded on a `CustodyEvent` when a transition writes it) but never compares it to any entity's `id`.

The remaining two roles are entity-backed and therefore carry ownership scope. When `X-User-Role` is `ClinicStaff`, `X-User-ID` is the `id` of the acting `Clinic`; ownership checks on any resource that references a clinic compare the resource's `clinic_id` to `X-User-ID`, so a `ClinicStaff` principal may submit intakes only for its own clinic and may read only its own clinic's cases, invoices, statement, and custody events. When `X-User-Role` is `PetOwner`, `X-User-ID` is the `id` of the acting `PetOwner`; ownership checks on any resource that references an owner compare the resource's `owner_id` to `X-User-ID`, so a `PetOwner` may view only their own pet's case, custody chain, certificate, and return routes, and may pay only their own owner-billed invoice. Any attempt by an entity-backed principal to read or act on another party's resource is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

List endpoints accept two query parameters to page through results. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must fall between a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip; when omitted it defaults to 0, and it must be greater than or equal to 0. A `limit` outside the range 1 through 100, or an `offset` below 0, is rejected with `ERR_PAGINATION_INVALID` (HTTP 422).

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order; because the logical clock can be frozen, two resources may share an identical `created_at`, and such ties are broken by the order in which the resources were created (earliest-created first). List responses include the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at its initial value and increments by one on each mutation. These full audit fields are present on `Clinic`, `PetOwner`, `Cooler`, `Retort`, `CremationBatch`, `Case`, `TransportLeg`, `KeepsakeOrder`, `ReturnRoute`, `MemorialAddon`, and `Invoice`.

Two resources are deliberately append-only and therefore minimal: the `CustodyEvent` and the `CertificateRecord` carry only `id` and `created_at`. Neither one exposes an `updated_at` field nor a `version` field, because once written they are never modified.

### 2.5. Hierarchical Consistency and Derived-Field Reconciliation

Many operations mutate more than one resource. Whenever a transition's side effects touch a related resource — incrementing a cooler's occupancy, recomputing a batch's loaded weight, adjusting a clinic's balance — that related resource is itself a mutation: its `updated_at` is refreshed and its `version` increments by one, exactly as the directly addressed resource's does. Derived fields are never client-supplied; they are recomputed by the server from their inputs whenever a triggering event occurs, so that fields such as a cooler's `occupied_count`, `available_capacity`, and `status`, or a clinic's `outstanding_balance_cents` and `account_status`, always reflect current reality. When a parent transition cascades into child resources (for example, a batch completion that drives each staged case to its cremated state), each affected child is mutated independently and carries its own refreshed `updated_at` and incremented `version`.

### 2.6. Nested Resource Retrieval and Path Validation

Several resources are reached through a parent path — a case's transport legs, custody events, keepsake orders, certificates, return routes, memorial add-ons, and invoices all hang off a case identifier; a batch's member cases hang off a batch identifier. For any request whose path contains more than one resource identifier, the server validates each identifier from left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not name an existing resource. The same `ERR_NOT_FOUND` applies when a foreign-key target supplied in a request body — a `clinic_id`, `owner_id`, `cooler_id`, `retort_id`, or `case_id` — does not name an existing resource.

### 2.7. Pricing Precision and Rounding

All monetary amounts in the system are integer cents. Where a calculation produces a fractional cent — specifically the weight-proportional allocation of a communal firing cost — the result is rounded half up to a whole cent. Aggregated balances (a clinic's outstanding balance, a clinic statement total) are integer sums of cents and are never negative; any computation that would yield a negative balance is floored at zero. Likewise, a cooler's available capacity is floored at zero and never reported as a negative number.

### 2.8. Optimistic Concurrency on Invoice Issuance

Issuing an invoice for a case is the one write in this system guarded by optimistic concurrency control. A request to issue an invoice for a case must carry `expected_case_version`, a non-optional field whose value is the `version` of the target `Case` that the client last observed. The server compares `expected_case_version` against the case's current `version`. If another writer has advanced the case's version since the client last read it — most importantly, by having already issued an invoice for that same case, which legitimately moves the case's billing state forward and increments its `version` — then the client's `expected_case_version` no longer matches, and the request is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). This prevents a client operating on a stale view of the case from creating a second, superseding invoice. No other endpoint in the system accepts or requires a version field; only invoice issuance is version-checked.

### 2.9. Logical Clock

The server keeps a logical clock that supplies every system-stamped timestamp: a custody event's `occurred_at`, a certificate's `cremated_at`, and the basis for all scheduling comparisons. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it reports that default rather than ever falling back to wall-clock time. An admin-only test-driving capability advances the clock to a supplied `to_iso8601` instant. All windowed scheduling logic (retort firing windows, viewing-room windows) is evaluated against this logical clock.

### 2.10. Validation Precedence

When a single request could fail more than one check, the checks are evaluated in a fixed order so that the returned `error_id` is deterministic. Authentication is evaluated first: a missing or unknown-role request fails with `ERR_UNAUTHENTICATED` before anything else. Authorization by role is evaluated next, failing with `ERR_FORBIDDEN`. Existence of every path-referenced resource and every body foreign-key target is checked third, failing with `ERR_NOT_FOUND`. Request well-formedness — required body fields present and correctly typed, enum values legal, numbers within their declared bounds — is checked fourth, failing with `ERR_INVALID_REQUEST` (HTTP 422). Ownership scope for entity-backed principals is checked fifth, failing with `ERR_FORBIDDEN`. After these generic gates, endpoint-specific business rules apply in the order described in Section 3; among them, the account-billing prerequisite is checked before the optimistic-concurrency version check, which is checked before the target's state is checked for transition validity, which in turn precedes the domain safety, capacity, scheduling, and fiscal checks. The detailed business rules and their specific error codes live with the workflows they guard in Section 3.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Crematory: Clinics, Owners, Coolers, and Retorts

Before any case can flow, a `CrematoryAdmin` provisions the standing resources. A clinic account is created with a `name` and a globally unique `account_code`, and optionally a `credit_limit_cents` that defaults to 500000 (five thousand dollars) when not supplied. A new clinic starts with an `outstanding_balance_cents` of 0 and an `account_status` of `CURRENT`. The account status is a derived label: a clinic is `DELINQUENT` whenever its outstanding balance strictly exceeds its credit limit, and `CURRENT` otherwise. The outstanding balance itself is the sum of `total_cents` over that clinic's invoices that are billed to the clinic account and still in the issued state; it is recomputed whenever an invoice is issued, voided, or paid, and is never negative.

A pet owner record is created with a `full_name`, a globally unique `email`, and a `phone`. Any of the crematory or clinic roles may create owners; this is the one creation a `ClinicStaff` principal performs outside of its own clinic's case flow.

Cooler units are refrigerated holding for bodies awaiting cremation. A cooler is created with a `label` and a `total_capacity` of at least 1 body slot. On creation a cooler reports an `occupied_count` of 0, an `available_capacity` equal to its total capacity, and a `status` of `AVAILABLE`. The occupied count is the number of cases currently held in that cooler — that is, cases whose `cooler_id` points at it and whose custody is in the in-cooler state. Available capacity is the total capacity minus the occupied count, floored at zero. A cooler's status is `FULL` when its occupied count is at least its total capacity, and `AVAILABLE` otherwise; the status therefore cycles `AVAILABLE` → `FULL` as a body enters that brings occupancy up to capacity, and back `FULL` → `AVAILABLE` as a slot frees.

A retort is a cremation oven, created with a `label` and a `max_load_lbs` of at least 1 pound, the maximum combined body weight it may fire in a single firing.

### 3.2. Intake: Opening a Case and Its Chain of Custody

A case is the central record tracking one deceased pet. A `CrematoryOperator` or a `ClinicStaff` principal opens a case by providing the `owner_id` of the bereaved owner, the `pet_name`, the `species` (one of `DOG`, `CAT`, or `OTHER`), the `weight_lbs` (an integer of at least 1 pound), the `service_type` (`PRIVATE` or `COMMUNAL`), the `pickup_kind` (`CLINIC` or `HOME`, indicating where the body is collected), and the `bill_to` party (`CLINIC_ACCOUNT` or `OWNER`). A `clinic_id` is supplied when the clinic submitted the intake and is left null for a direct owner drop-off. An `expedited` flag may be supplied and defaults to false; when true it adds an expedite surcharge to a private cremation charge. A `PRIVATE` case returns this individual pet's ashes; a `COMMUNAL` case pools the remains with others and is disposed rather than returned.

If `bill_to` is `CLINIC_ACCOUNT`, the case must carry a `clinic_id`; an account-billed intake without a clinic is rejected with `ERR_CLINIC_REQUIRED_FOR_ACCOUNT_BILLING` (HTTP 422).

On creation the case begins in custody `INTAKE_PENDING` and billing `NOT_BILLABLE`, its `cremation_charge_cents` is 0 until a firing determines it, its `custody_chain_open` flag is true, and it has not yet been assigned a `batch_id` or a `cooler_id` (both null until later steps set them). The server immediately appends the first custody event of type `INTAKE` to the case's chain. Every custody event carries a per-case `seq` that starts at 1 and increases by one for each appended event, defining the chain's order; an `event_type`; the `custodian` holding the body at that hop; and an `occurred_at` taken from the logical clock. The case also derives a `weight_tier` from its weight, described in Section 3.9, and a `custody_chain_open` flag that stays true until a terminal custody event (a return to owner, a communal disposition, or a cancellation) closes the chain.

The two case axes — `custody_status` and `billing_status` — evolve independently. The custody axis tracks the body's physical journey; the billing axis tracks revenue recognition and payment. A case's full custody vocabulary is `INTAKE_PENDING`, `IN_TRANSIT`, `RECEIVED`, `IN_COOLER`, `STAGED`, `CREMATED`, `READY_FOR_RETURN`, `RETURNED`, and `CANCELLED`, with `RETURNED` and `CANCELLED` terminal. Its billing vocabulary is `NOT_BILLABLE`, `BILLABLE`, `INVOICED`, and `SETTLED`, with `SETTLED` terminal.

### 3.3. Transport and Receiving

A `CrematoryOperator` dispatches collection by creating the case's first transport leg, which is permitted only while the case is in `INTAKE_PENDING`. The request supplies the `origin_kind` (`CLINIC` or `HOME`), a free-text `origin_label` naming the pickup address or clinic, and the `driver_name`. Creating the leg advances the case from `INTAKE_PENDING` to `IN_TRANSIT`, creates a `TransportLeg` in status `ASSIGNED`, appends a `TRANSPORT_PICKUP` custody event whose custodian is the driver's name, refreshes the case's `updated_at`, and increments the case's `version` by one.

A transport leg advances through its own linear lifecycle, driven by the operator via the leg's `status` field: `ASSIGNED` → `EN_ROUTE` when the driver departs, and `EN_ROUTE` → `ARRIVED` on arrival. From either `ASSIGNED` or `EN_ROUTE` a leg may be cancelled to `CANCELLED`. Each of these transitions refreshes the leg's `updated_at` and increments its `version`. The terminal states are `ARRIVED` and `CANCELLED`. Attempting a leg transition that the current status does not allow is rejected with `ERR_INVALID_STATE` (HTTP 409).

Receiving the body at the facility moves the case from `IN_TRANSIT` to `RECEIVED`. This requires both that the case currently be `IN_TRANSIT` and that the case have a transport leg already in the `ARRIVED` status; if the chain prerequisite is not met — for instance, no arrived leg backing the receive — the request is rejected with `ERR_CUSTODY_CHAIN_BROKEN` (HTTP 409). Receiving appends a `RECEIVED_AT_FACILITY` custody event, refreshes `updated_at`, and increments the case's `version`. Receiving is also the moment the billing axis comes alive: as a system side effect the case's billing moves from `NOT_BILLABLE` to `BILLABLE`, recognizing the case as eligible for invoicing.

### 3.4. Cooler Storage

Once received, a body may be placed into refrigerated holding. Storing moves the case from `RECEIVED` to `IN_COOLER` and requires that the target cooler be `AVAILABLE` (equivalently, that its occupied count be below its total capacity); the request names the target via a `cooler_id`. A store against a cooler whose occupied count has already reached its total capacity is rejected with `ERR_COOLER_FULL` (HTTP 409). A store attempted when the case's custody chain prerequisite is not satisfied is rejected with `ERR_CUSTODY_CHAIN_BROKEN`. A successful store sets the case's `cooler_id` to the target cooler, increments that cooler's `occupied_count` by one, recomputes the cooler's `available_capacity` and `status` (flipping `AVAILABLE` → `FULL` if the occupied count has reached total capacity), appends a `COOLER_IN` custody event whose custodian is the cooler's label, refreshes the case's `updated_at`, and increments the case's `version`. The cooler is itself mutated and carries a refreshed `updated_at` and incremented `version`.

### 3.5. Staging into a Cremation Batch

A cremation batch groups one or more cases for a single firing in a particular oven. A `CrematoryOperator` or `CrematoryAdmin` creates a batch with a `retort_id` naming the oven, a `service_type` (`PRIVATE` or `COMMUNAL`), a `scheduled_start`, and a `scheduled_end`. The firing window runs from `scheduled_start` (inclusive) to `scheduled_end` (exclusive), so the end must be strictly after the start; a window whose end is at or before its start is rejected with `ERR_SCHEDULE_WINDOW_INVALID` (HTTP 422). A `PRIVATE` batch holds exactly one case and returns that pet's ashes; a `COMMUNAL` batch holds one or more cases whose remains are pooled. A new batch starts in status `OPEN` with a `member_count` of 0, a `loaded_weight_lbs` of 0, and a `communal_firing_total_cents` of 0. The batch's member count is the number of its cases that are not cancelled, and its loaded weight is the sum of `weight_lbs` over those same non-cancelled members; both are recomputed as members join or leave. A batch's status vocabulary is `OPEN`, `LOADED`, `FIRING`, `COMPLETED`, and `RECONCILED`, with `RECONCILED` terminal.

Staging assigns a case to a batch. The request names the case via a `case_id`. Staging is permitted only when the case is `RECEIVED` or `IN_COOLER`, the target batch is `OPEN`, and the case's `service_type` equals the batch's `service_type`. A case whose service type differs from the batch's, or an attempt to add a second member to a `PRIVATE` batch that already holds one, is rejected with `ERR_SERVICE_TYPE_MISMATCH` (HTTP 409). A staging attempt whose custody chain prerequisite is unmet is rejected with `ERR_CUSTODY_CHAIN_BROKEN`. A successful staging moves the case to `STAGED`, sets the case's `batch_id` to the target batch, and appends a `STAGED` custody event. If the case was `IN_COOLER` at the time it is staged, the system also clears its `cooler_id`, decrements the holding cooler's `occupied_count`, recomputes that cooler's `available_capacity` and `status` (flipping `FULL` → `AVAILABLE` when a slot frees), and appends a `COOLER_OUT` custody event before the `STAGED` event. The batch's `member_count` and `loaded_weight_lbs` are recomputed, the case's `updated_at` is refreshed, and the case's `version` increments.

### 3.6. Firing: Loading, Igniting, and Completing a Batch

Firing a batch is a three-step floor procedure carried out by a `CrematoryOperator`. First the batch is loaded, moving it from `OPEN` to `LOADED`. Loading requires that the batch be `OPEN`, that it have at least one member, and that its loaded weight not exceed the retort's maximum load. A load on a batch with no members is rejected with `ERR_BATCH_EMPTY` (HTTP 409); a load whose `loaded_weight_lbs` exceeds the retort's `max_load_lbs` is rejected with `ERR_RETORT_OVERLOADED` (HTTP 409). For a `PRIVATE` batch, loading additionally requires that the member count be exactly one. Loading refreshes `updated_at` and increments the batch's `version`.

Igniting the batch moves it from `LOADED` to `FIRING`. Firing requires the batch be `LOADED` and have at least one member; a fire on an empty batch is rejected with `ERR_BATCH_EMPTY`. Firing also requires that no other batch on the same retort already occupy an overlapping firing window while in the `FIRING` status. Two windows are treated as half-open intervals `[scheduled_start, scheduled_end)`: they conflict when they overlap, but windows that merely touch at an endpoint (one ending exactly when another begins) do not conflict. A fire that would overlap another firing batch on the same retort is rejected with `ERR_RETORT_WINDOW_CONFLICT` (HTTP 409). Firing is the moment cremation charges are determined, as detailed in Section 3.9; it then refreshes `updated_at` and increments the batch's `version`.

Completing the firing moves the batch from `FIRING` to `COMPLETED`. Completion cascades into every member case that is in the `STAGED` custody state, driving each from `STAGED` to `CREMATED`: for each such case the system appends a `CREMATED` custody event (custodian being the operator) and issues a certificate record in the `ISSUED` status bearing the next sequential `certificate_number`. A member that had been `IN_COOLER` released its cooler slot back at staging time, so completion makes no further cooler change. Each cremated case has its `updated_at` refreshed and its `version` incremented, and the batch likewise refreshes `updated_at` and increments its `version`.

A certificate record is an append-only attestation. When issued it captures the next `certificate_number` in sequence — a server-wide monotonic counter rendered as a decimal string, beginning at `"1"` for the first certificate issued and incrementing by one for each subsequent certificate — a snapshot of the case's `pet_name` and `service_type` as they stood at issuance, a `cremated_at` drawn from the logical clock at the moment the cremation completed, and a `status` of `ISSUED`; the only other status it may bear is `VOID`.

### 3.7. Reconciliation and Communal Disposition

After completion, a `CrematoryAdmin` reconciles the batch, moving it from `COMPLETED` to `RECONCILED`. Reconciliation is permitted only when every member case has reached `CREMATED`, `READY_FOR_RETURN`, or `RETURNED`. For a `COMMUNAL` batch, reconciliation is the disposition point: every member case still in `CREMATED` receives a `DISPOSED_COMMUNAL` custody event and has its `custody_chain_open` flag set to false, closing its chain since communal remains are pooled and not returned. Reconciliation refreshes the batch's `updated_at` and increments its `version`.

### 3.8. Return of Ashes for Private Cases

A private case's ashes are returned to the owner through a two-step closure. First, once a case is `CREMATED` and has an issued certificate, a `CrematoryOperator` marks it ready for return, moving it from `CREMATED` to `READY_FOR_RETURN`. This step creates a `ReturnRoute` in the `PLANNED` status from the request's `return_method` and `destination_label`, where `return_method` is one of `PICKUP_AT_FACILITY`, `COURIER_TO_CLINIC`, or `COURIER_TO_HOME`, and `destination_label` names the drop-off address or pickup contact. The case's `updated_at` is refreshed and its `version` increments.

A return route advances through `PLANNED`, `DISPATCHED`, `DELIVERED`, and `CANCELLED`, the last two terminal. The operator dispatches a planned route, moving it `PLANNED` → `DISPATCHED`, which requires both that the route be `PLANNED` and that its owning case be in `READY_FOR_RETURN`. Either the operator may cancel a route from `PLANNED` or `DISPATCHED` to `CANCELLED`. Every route transition refreshes `updated_at` and increments the route's `version`.

Finalizing the return moves the case from `READY_FOR_RETURN` to `RETURNED`. This requires that the case be `READY_FOR_RETURN`, that its `service_type` be `PRIVATE` (communal cases are disposed at reconciliation, never returned), and that it have a return route currently in the `DISPATCHED` status. Finalizing cascades that route from `DISPATCHED` to `DELIVERED`, appends a `RETURN_TO_OWNER` custody event, sets the case's `custody_chain_open` to false, refreshes `updated_at`, and increments the case's `version`. Any custody transition attempted from a state that does not permit it is rejected with `ERR_INVALID_STATE`.

### 3.9. Pricing a Cremation

A case's `weight_tier` is derived from its `weight_lbs` the moment the weight is set, using inclusive upper bounds measured in whole pounds: a case weighing 25 pounds or less is `SMALL`; from 26 through 75 pounds inclusive it is `MEDIUM`; from 76 through 150 pounds inclusive it is `LARGE`; and above 150 pounds it is `XLARGE`. The boundaries are inclusive on the upper edge, so a 25-pound pet is `SMALL` while a 26-pound pet is `MEDIUM`.

The `cremation_charge_cents` for every member case is determined at the instant its batch is fired (the `LOADED` → `FIRING` transition), and is 0 until then. The two service types price differently. For a `PRIVATE` batch — which holds the single member — the charge is the flat tier rate for that pet's weight tier plus the expedite surcharge if the case is expedited: 12000 cents for `SMALL`, 18000 for `MEDIUM`, 26000 for `LARGE`, and 38000 for `XLARGE`, with an additional 5000 cents added when the `expedited` flag is true. A private firing leaves the batch's `communal_firing_total_cents` at 0.

For a `COMMUNAL` batch, a fixed pooled firing cost of 30000 cents is recorded as the batch's `communal_firing_total_cents` and then allocated across all member cases (those not cancelled) in proportion to body weight. The allocation is computed by first summing the weights of all members. For each member, its raw share is the pooled total of 30000 cents multiplied by that member's weight and divided by the total weight; that raw share is rounded half up to a whole cent, and this per-case rounding happens before any summation. Because rounding each share independently may leave the sum of shares off the pooled total by a few cents in either direction, the remainder — the pooled total minus the sum of the rounded shares — is added to the share of the last member when members are ordered by their creation timestamp ascending, with ties on an identical `created_at` (as occurs under a frozen logical clock) broken by creation order so that the most recently created member is the one treated as last and absorbs the remainder. Each member's resulting share becomes its `cremation_charge_cents`.

### 3.10. Invoicing a Case

Invoicing is the billing-axis counterpart to firing, and it is performed by a `CrematoryAdmin`. A case may be invoiced only when its billing status is `BILLABLE` and its custody status is `CREMATED` — that is, invoicing happens only after cremation completes. The invoice-issue request carries `expected_case_version` for the optimistic-concurrency check described in Section 2.8; a mismatch with the case's current `version` is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). Issuing an invoice that would push a clinic-account clinic's outstanding balance above its credit limit is rejected with `ERR_CLINIC_CREDIT_EXCEEDED` (HTTP 409).

A successful issuance creates an `Invoice` in the `ISSUED` status, snapshotting the case's `bill_to` onto the invoice and, when account-billed, the `clinic_id`; the invoice records the `case_id` it bills. It computes the invoice's `subtotal_cents`, `handling_fee_cents`, and `total_cents` in that pinned order. The subtotal is the case's `cremation_charge_cents` plus the sum of `unit_price_cents` over the case's keepsake orders that are not cancelled plus the sum of `price_cents` over the case's memorial add-ons that are not cancelled. The handling fee depends on who is billed: for a `CLINIC_ACCOUNT` invoice the handling fee is waived at 0. For an `OWNER` invoice the fee is tiered on the subtotal — 2500 cents when the subtotal is below 20000 cents, 1500 cents when the subtotal is from 20000 through 50000 cents inclusive, and 0 cents when the subtotal is above 50000 cents. The total is the subtotal plus the handling fee; for a clinic-account invoice, where the fee is 0, the total therefore equals the subtotal.

Issuing the invoice moves the case's billing from `BILLABLE` to `INVOICED`, refreshes the case's `updated_at`, and increments the case's `version` (this increment is precisely what makes a stale-version second issuance fail). When the invoice is billed to a clinic account, the clinic's `outstanding_balance_cents` increases by the invoice's `total_cents` and the clinic's `account_status` is recomputed (becoming `DELINQUENT` if the balance now exceeds the credit limit).

### 3.11. Paying and Voiding Invoices

An issued invoice may be paid or voided; both are terminal moves off the `ISSUED` status, to `PAID` and `VOID` respectively. Paying an invoice may be done by a `CrematoryAdmin` or, for an owner-billed invoice, by the `PetOwner` who owns it, and is permitted only while the invoice is `ISSUED`. Payment cascades the case's billing from `INVOICED` to `SETTLED`. When the paid invoice is account-billed, the clinic's `outstanding_balance_cents` is decreased by the invoice's `total_cents` and its `account_status` is recomputed (returning from `DELINQUENT` to `CURRENT` if the balance falls to or below the credit limit). Payment refreshes the invoice's `updated_at` and increments its `version`.

Voiding an issued invoice is reserved for a `CrematoryAdmin` and is likewise permitted only while the invoice is `ISSUED`. Voiding cascades the case's billing from `INVOICED` back to `BILLABLE`, making the case eligible to be invoiced again. When the voided invoice is account-billed, the clinic's `outstanding_balance_cents` is decreased by the invoice's `total_cents` and its `account_status` is recomputed. Voiding refreshes the invoice's `updated_at` and increments its `version`. A re-trigger of a pay or void on an invoice that is no longer `ISSUED` is rejected with `ERR_INVALID_STATE`.

### 3.12. Keepsakes and Memorial Add-Ons

Throughout a case's life a `CrematoryOperator` or `ClinicStaff` principal may order keepsakes — physical mementos created from the pet. A keepsake order names its `item_type`, one of `PAW_PRINT`, `CLAY_IMPRESSION`, `FUR_CLIPPING`, `URN`, or `PENDANT`, and is priced at the catalog rate for that item into its `unit_price_cents`: 4500 cents for `PAW_PRINT`, 5500 for `CLAY_IMPRESSION`, 2000 for `FUR_CLIPPING`, 8000 for `URN`, and 9500 for `PENDANT`. A keepsake order starts in `ORDERED` and advances through `IN_PRODUCTION` to `READY`, each step driven by a `status` change made by an operator; the terminal states are `READY` and `CANCELLED`. A keepsake order may be cancelled from `ORDERED` or `IN_PRODUCTION`, but only while the case has no issued invoice; cancelling a priced line item after the case has been invoiced is rejected with `ERR_LINE_ITEM_LOCKED` (HTTP 409). Each transition refreshes `updated_at` and increments the keepsake order's `version`.

Memorial add-ons are services attached to a case, again orderable by a `CrematoryOperator` or `ClinicStaff` principal. An add-on names its `addon_type`, one of `ONLINE_MEMORIAL`, `VIEWING_SESSION`, or `TRIBUTE_VIDEO`, and is priced into its `price_cents` from the catalog: 3000 cents for `ONLINE_MEMORIAL`, 12000 for `VIEWING_SESSION`, and 7000 for `TRIBUTE_VIDEO`. An add-on starts in `BOOKED` and may move to `FULFILLED`, or be cancelled to `CANCELLED`; the terminal states are `FULFILLED` and `CANCELLED`. As with keepsakes, an add-on may be cancelled only while the case has no issued invoice, otherwise the cancellation is rejected with `ERR_LINE_ITEM_LOCKED`. Each transition refreshes `updated_at` and increments the add-on's `version`.

A `VIEWING_SESSION` add-on is a scheduled, room-bound event and therefore carries extra requirements. When the `addon_type` is `VIEWING_SESSION`, the request must supply a `viewing_room_code` (such as `ROOM-1`), a `viewing_start`, and a `viewing_end`, and the end must be strictly after the start; a viewing session missing any of these fields, or whose viewing end is at or before its viewing start, is rejected with `ERR_VIEWING_FIELDS_REQUIRED` (HTTP 422). For non-viewing add-on types these three fields are left null. Booking a viewing session also enforces room scheduling: the requested viewing window, extended by a viewing buffer of fifteen minutes on each side (its `viewing_start` moved fifteen minutes earlier and its `viewing_end` fifteen minutes later), must not collide with any other non-cancelled viewing session already booked in the same `viewing_room_code` whose own window is likewise extended by the fifteen-minute buffer on each side. The two buffered windows are compared as half-open intervals — they collide when they overlap, but windows that merely touch at an endpoint after buffering do not collide. A booking whose buffered window collides with another viewing in the same room is rejected with `ERR_VIEWING_ROOM_CONFLICT` (HTTP 409).

### 3.13. Cancelling a Case

A case may be cancelled before cremation by a `CrematoryOperator` or `CrematoryAdmin`. Cancellation is permitted only while the case is in `INTAKE_PENDING`, `IN_TRANSIT`, `RECEIVED`, `IN_COOLER`, or `STAGED`, and additionally requires that the case either have no batch assigned or be in a batch still `OPEN` — a case in a `FIRING` or `COMPLETED` batch can no longer be cancelled. An attempt to cancel a case outside these custody states is rejected with `ERR_INVALID_STATE`.

Cancellation unwinds the case's footprint in a single operation. If the case was `IN_COOLER`, the system clears its `cooler_id`, decrements the holding cooler's `occupied_count`, recomputes that cooler's `available_capacity` and `status`, and appends a `COOLER_OUT` custody event. If the case was `STAGED`, the system clears its `batch_id` and recomputes the former batch's `member_count` and `loaded_weight_lbs`. Any transport leg not already cancelled is moved to `CANCELLED`. Any issued invoice for the case is voided, moving it to `VOID`; when that invoice was clinic-billed, the clinic's `outstanding_balance_cents` and `account_status` are recomputed accordingly. Finally a `CANCELLED` custody event is appended, the case's `custody_chain_open` is set to false, its `updated_at` is refreshed, and its `version` increments.

### 3.14. Clinic Statements: Two Recognition Bases

A clinic's account holders can request a computed statement balance under a chosen recognition basis, supplied as a `basis` query parameter that is either `ACCRUAL` or `COMPLETION`; when the `basis` parameter is omitted it defaults to `COMPLETION` (a `basis` value other than `ACCRUAL` or `COMPLETION` is rejected with `ERR_INVALID_REQUEST`). The statement considers only that clinic's cases billed to the clinic account, and sums their `cremation_charge_cents` over the cases that qualify under the chosen basis. Under the `ACCRUAL` basis a case's charge is recognized once the body has been received, so the sum includes every clinic-account case whose custody status is `RECEIVED`, `IN_COOLER`, `STAGED`, `CREMATED`, `READY_FOR_RETURN`, or `RETURNED`. Under the `COMPLETION` basis recognition waits for cremation, so the sum includes only clinic-account cases whose custody status is `CREMATED`, `READY_FOR_RETURN`, or `RETURNED`. Because a case's cremation charge stays 0 until its batch fires, an accrual-recognized case that is still `STAGED` contributes 0; the two bases diverge only once charges have been set on cases that have been received but not yet cremated. The statement response reports the `clinic_id`, the chosen `basis`, and the resulting `balance_cents` as an integer sum of cents. This is a read-only report and mutates nothing.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including state transitions and the logical-clock setter — return `200 OK`. All endpoints require the `X-User-ID` and `X-User-Role` headers described in Section 2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | CrematoryAdmin |
| POST | `/clinics` | Create a clinic account | CrematoryAdmin |
| GET | `/clinics/{id}` | Get a clinic | CrematoryAdmin, CrematoryOperator, ClinicStaff |
| GET | `/clinics` | List clinics | CrematoryAdmin, CrematoryOperator |
| GET | `/clinics/{id}/statement` | Computed clinic statement balance under a recognition basis | CrematoryAdmin, ClinicStaff |
| POST | `/petowners` | Create a pet owner | CrematoryAdmin, CrematoryOperator, ClinicStaff |
| GET | `/petowners/{id}` | Get a pet owner | CrematoryAdmin, CrematoryOperator, ClinicStaff, PetOwner |
| POST | `/coolers` | Create a cooler unit | CrematoryAdmin |
| GET | `/coolers/{id}` | Get a cooler | CrematoryAdmin, CrematoryOperator |
| GET | `/coolers` | List coolers | CrematoryAdmin, CrematoryOperator |
| POST | `/retorts` | Create a cremation retort | CrematoryAdmin |
| GET | `/retorts/{id}` | Get a retort | CrematoryAdmin, CrematoryOperator |
| POST | `/batches` | Create a cremation batch on a retort | CrematoryOperator, CrematoryAdmin |
| GET | `/batches/{id}` | Get a cremation batch | CrematoryAdmin, CrematoryOperator |
| GET | `/batches` | List cremation batches | CrematoryAdmin, CrematoryOperator |
| GET | `/batches/{id}/cases` | List member cases of a batch | CrematoryAdmin, CrematoryOperator |
| POST | `/batches/{id}/assign-case` | Assign (stage) a case to this batch | CrematoryOperator |
| POST | `/batches/{id}/load` | Mark the batch loaded | CrematoryOperator |
| POST | `/batches/{id}/fire` | Fire the batch; allocate cremation charges | CrematoryOperator |
| POST | `/batches/{id}/complete` | Complete the firing; cascade members to cremated | CrematoryOperator |
| POST | `/batches/{id}/reconcile` | Reconcile a completed batch | CrematoryAdmin |
| POST | `/cases` | Create an intake case | CrematoryOperator, ClinicStaff |
| GET | `/cases/{id}` | Get a case | CrematoryAdmin, CrematoryOperator, ClinicStaff, PetOwner |
| GET | `/cases` | List cases | CrematoryAdmin, CrematoryOperator, ClinicStaff, PetOwner |
| POST | `/cases/{id}/transport-legs` | Create a transport leg | CrematoryOperator |
| GET | `/cases/{id}/transport-legs` | List transport legs for a case | CrematoryAdmin, CrematoryOperator |
| PATCH | `/transport-legs/{id}` | Advance or cancel a transport leg | CrematoryOperator |
| GET | `/transport-legs/{id}` | Get a transport leg | CrematoryAdmin, CrematoryOperator |
| GET | `/cases/{id}/custody-events` | List the chain-of-custody events for a case in seq order | CrematoryAdmin, CrematoryOperator, ClinicStaff, PetOwner |
| POST | `/cases/{id}/receive` | Receive the body at the facility | CrematoryOperator |
| POST | `/cases/{id}/store` | Store the body in a cooler | CrematoryOperator |
| POST | `/cases/{id}/ready-return` | Mark a private case ready for return | CrematoryOperator |
| POST | `/cases/{id}/finalize-return` | Finalize the ashes return | CrematoryOperator |
| POST | `/cases/{id}/cancel` | Cancel a case before cremation | CrematoryOperator, CrematoryAdmin |
| POST | `/cases/{id}/invoices` | Issue an invoice for a cremated case | CrematoryAdmin |
| GET | `/cases/{id}/invoices` | List invoices for a case | CrematoryAdmin, CrematoryOperator, ClinicStaff, PetOwner |
| POST | `/cases/{id}/keepsake-orders` | Order a keepsake for a case | CrematoryOperator, ClinicStaff |
| GET | `/cases/{id}/keepsake-orders` | List keepsake orders for a case | CrematoryAdmin, CrematoryOperator, ClinicStaff, PetOwner |
| PATCH | `/keepsake-orders/{id}` | Advance or cancel a keepsake order | CrematoryOperator |
| GET | `/cases/{id}/certificates` | List certificate records for a case | CrematoryAdmin, CrematoryOperator, ClinicStaff, PetOwner |
| GET | `/cases/{id}/return-routes` | List return routes for a case | CrematoryAdmin, CrematoryOperator, ClinicStaff, PetOwner |
| POST | `/return-routes/{id}/dispatch` | Dispatch a planned return route | CrematoryOperator |
| POST | `/return-routes/{id}/cancel` | Cancel a return route | CrematoryOperator |
| POST | `/cases/{id}/memorial-addons` | Add a memorial add-on to a case | CrematoryOperator, ClinicStaff |
| GET | `/cases/{id}/memorial-addons` | List memorial add-ons for a case | CrematoryAdmin, CrematoryOperator, ClinicStaff, PetOwner |
| PATCH | `/memorial-addons/{id}` | Fulfill or cancel a memorial add-on | CrematoryOperator |
| GET | `/invoices/{id}` | Get an invoice | CrematoryAdmin, CrematoryOperator, ClinicStaff, PetOwner |
| GET | `/invoices` | List invoices | CrematoryAdmin, CrematoryOperator, ClinicStaff |
| POST | `/invoices/{id}/pay` | Pay an issued invoice | CrematoryAdmin, PetOwner |
| POST | `/invoices/{id}/void` | Void an issued invoice | CrematoryAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_CLINIC_REQUIRED_FOR_ACCOUNT_BILLING` | 422 |
| `ERR_STALE_CASE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SERVICE_TYPE_MISMATCH` | 409 |
| `ERR_CUSTODY_CHAIN_BROKEN` | 409 |
| `ERR_RETORT_WINDOW_CONFLICT` | 409 |
| `ERR_VIEWING_ROOM_CONFLICT` | 409 |
| `ERR_RETORT_OVERLOADED` | 409 |
| `ERR_COOLER_FULL` | 409 |
| `ERR_BATCH_EMPTY` | 409 |
| `ERR_CLINIC_CREDIT_EXCEEDED` | 409 |
| `ERR_LINE_ITEM_LOCKED` | 409 |
| `ERR_PAGINATION_INVALID` | 422 |
| `ERR_VIEWING_FIELDS_REQUIRED` | 422 |
| `ERR_SCHEDULE_WINDOW_INVALID` | 422 |
