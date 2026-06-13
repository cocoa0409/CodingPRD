# Document Shredding & Records Storage API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Document Shredding & Records Storage API, a back-office platform for a secure-destruction and records-management business. The operator runs a mixed fleet of services: on-site mobile shredding at customer sites, off-site pickup with destruction at a central plant, customer drop-off intake, scheduled recurring purges of locked consoles and rolling bins, one-time bulk purges, and a long-term retention warehouse where sealed boxes are shelved, retrieved on demand, and eventually destroyed once their legal retention clock has elapsed. Each of these flows carries a different custody trail, a different pricing variant, and a different compliance obligation, and the platform's central job is to keep all three coherent.

The business operates under regulatory regimes — most importantly HIPAA and FACTA — that demand an unbroken, tamper-evident chain of custody and a defensible certificate of destruction for every kilogram of material destroyed. Two practical consequences flow from this. First, the operator who physically collects material may never be the same person who witnesses its final destruction; this segregation of duties is a hard rule, not a guideline. Second, any box or order can be frozen by a legal or regulatory hold, and while that hold is active no destruction may proceed. The API encodes these obligations as enforced preconditions so that an audit can be satisfied from the system of record alone.

Billing is woven through every workflow. Destruction work is priced by weight against a per-account rate card, first provisionally at the estimated nominal weight and then finally at the actual weighed net; retention boxes accrue a recurring per-period storage charge once their free period elapses; and retrievals carry a flat fee with a rush surcharge. Invoices — both per-destruction and per-period storage — are emitted automatically as the relevant workflow milestones are reached, and a deterministic billing clock advances one period at a time under explicit operator control.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint. Where a rule reads as a domain behavior tied to a specific workflow, its full statement lives in Section 3; this section establishes the invariants every reader must assume everywhere.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting operator, and `X-User-Role` declares the operational capacity under which they are acting. If either header is absent or malformed, the request is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401); a header whose value is empty (or whitespace-only) after trimming, and an `X-User-Role` whose value is not one of the recognized roles below, both count as malformed and likewise yield `ERR_MISSING_AUTH_CONTEXT` (HTTP 401) — `ERR_FORBIDDEN_ROLE` is reserved for a recognized role that merely lacks permission for the operation. If the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly five roles, spelled precisely as follows: `ComplianceOfficer`, `AccountManager`, `FieldTechnician`, `PlantOperator`, and `DestructionWitness`. The `ComplianceOfficer` owns accounts, rate cards, compliance holds, certificate voids, billing periods, and invoice payment. The `AccountManager` is the customer-facing operator handling locations, orders, retrieval requests, purges, and cancellations. The `FieldTechnician` takes physical custody in the field — container placement, dispatch, weigh-in, on-site shredding, and pickup — and is the custody-taking side of the segregation-of-duties rule. The `PlantOperator` runs the plant and warehouse side: receiving at plant, weigh-in, shelving, retrieval fulfillment and return, and box ingest. The `DestructionWitness` is the independent witness who signs the final destruction and forms the counterparty side of segregation of duties.

For all five roles, `X-User-ID` is an opaque operator identifier and is not tied to any persisted entity; the server never compares it to any entity's `id` for ownership purposes. Instead, the server records the acting operator's identifier wherever a workflow captures it: the `FieldTechnician` identifier supplied as `assigned_tech_id` pins the custody-taker on an order, the operator who logs a custody hop is recorded as the chain's `actor_id`, the operator who records a weigh-in is recorded as `captured_by`, the requester of a retrieval is recorded as `requested_by`, and the witness who signs a destruction is recorded as `witnessed_by`. These captured identifiers are evidentiary records, not access-control subjects. The single place where a captured identifier is compared to another is the segregation-of-duties check at destruction (see Section 3), where the witnessing operator's identifier must differ from the order's recorded `assigned_tech_id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, and is constrained to a minimum of 1 and a maximum of 100 — a supplied `limit` below 1 is clamped up to 1 and a `limit` above 100 is clamped down to 100, rather than rejected. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0; a negative `offset` is clamped up to 0. A `limit` or `offset` that is absent, empty, or not parseable as an integer falls back silently to its default.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Audit Trail

Most resources in this system are durable, mutable records and carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every mutation. The `version` field is an integer that begins at creation and increments by one on every mutation; it is the basis for optimistic concurrency control where that applies. Service accounts, locations, rate cards, containers, service orders, destruction certificates, destruction invoices, retention boxes, retrieval requests, compliance holds, and storage invoices all carry this full set. Every entity that has a lifecycle exposes its current lifecycle state through a system-managed `status` field, whose permitted values are enumerated per entity in the workflows below.

Two entities are deliberate exceptions because they are append-only, immutable evidence rather than mutable records. A weight ticket and a custody event each carry only `id` and `created_at`; neither has an `updated_at` field nor a `version` field, and once written they are never modified. This is intentional: the weigh-in ticket and the chain-of-custody log must be tamper-evident, so they admit no in-place edits.

### 2.5. Chain-of-Custody and Cascade Consistency

Several operations mutate more than one entity, and the secondary effects are as much a part of the contract as the primary transition. Whenever an operation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented. Where an operation drives a second entity — for example, a retrieval fulfillment moving the box it targets, or an order transition moving the containers it services — the driven entity undergoes its own mutation with its own `updated_at` refresh and `version` increment. The custody chain is the spine of this consistency model: each custody hop appends a new immutable `CustodyEvent` rather than editing an existing one, and the cascade that issues a certificate and then an invoice at destruction is a fixed three-hop chain described in full in Section 3.

### 2.6. Resource Resolution Order

Endpoints reference resources both in the URL path and in the request body, and several reference more than one. The server validates referenced identifiers left to right and rejects on the first one that does not resolve, returning the not-found error specific to that resource: `ERR_ACCOUNT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_BOX_NOT_FOUND`, or `ERR_REQUEST_NOT_FOUND` for accounts, orders, boxes, and retrieval requests respectively, and the generic `ERR_NOT_FOUND` for any other referenced resource — a location, container, rate card, certificate, invoice, or hold. The polymorphic subjects are resolved the same way: a `subject_id` is looked up under the entity type named by its `subject_type`, and a `subject_id` that does not resolve to a live entity of that type yields `ERR_NOT_FOUND`. All resource collections are top-level; a parent is reached by filtering a list endpoint on the relevant foreign-key field (for instance, listing containers by `account_id` and `location_id`), never by a nested URL.

### 2.7. Monetary and Weight Precision

All money in this system is held in integer cents; there are no fractional cents, and every monetary field — rates, fees, charges, credits, and invoice lines — is a whole number of cents. Where a calculation multiplies a weight by a per-kilogram rate, or applies a basis-point multiplier, the product is rounded to the nearest integer cent using the round-half-up convention (a value exactly halfway between two integers rounds up). Weights are carried to three decimal places of a kilogram, also rounded half up, and a computed net weight is never allowed to fall below zero. Flat fees defined on the rate card are already integer cents and are used as-is.

### 2.8. Optimistic Concurrency on Rescheduling

Rescheduling a service order to a new slot is the one operation guarded by optimistic concurrency control. A reschedule request must carry `expected_serviceorder_version`, which is not optional; it must equal the target order's current `version` at the moment the request is processed. If another writer has advanced the order's `version` since the client last read it — for instance, because a competing reschedule has already superseded the prior slot — the supplied value is stale and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This stale-version check is evaluated before any slot-conflict checks, so a client acting on an out-of-date view of the order is turned away before the system considers slot geometry, and the rule determines which reschedule defines the live slot. No other endpoint accepts a version field, and no other endpoint performs this check.

### 2.9. Compliance Holds and Segregation of Duties

Two safety principles cut across the destruction and retrieval workflows. A compliance hold freezes its subject: while a hold is `ACTIVE`, the box or order it names cannot be destroyed, purged, dispatched, fulfilled, or taken in via a drop-off pickup. Segregation of duties keeps the custody-taker and the destruction witness distinct: the operator who collected an order's material may not also witness its destruction. The precise trigger conditions, the error codes, and the order in which these checks run relative to other preconditions are stated alongside the workflows they guard in Section 3.

### 2.10. Validation Ordering

When several validations apply to one operation, they are evaluated in a fixed priority order so that the rejection a client sees is deterministic. Authentication comes first: a missing or malformed auth context (`ERR_MISSING_AUTH_CONTEXT`) is caught before anything else, then role authorization (`ERR_FORBIDDEN_ROLE`). Existence of every referenced resource is checked next, left to right, yielding the appropriate not-found error. For a reschedule, the optimistic-concurrency stale-version check (`ERR_STALE_VERSION`) runs next, ahead of slot geometry. The state precondition — that the target is in a state from which the requested transition is defined — is checked next and yields the transition-specific conflict error from the state machine. Then come the business-safety checks: an active compliance hold on the subject (`ERR_SUBJECT_ON_HOLD`), and the segregation-of-duties check at destruction (`ERR_SEGREGATION_OF_DUTIES`). The retention-schedule check (`ERR_RETENTION_NOT_ELAPSED`) follows for purges. Temporal slot checks come next — the container slot-conflict check (`ERR_SLOT_CONFLICT`) and then the on-site buffer check (`ERR_ONSITE_BUFFER_CONFLICT`). Field-value sanity (`ERR_INVALID_FIELD_VALUE`) and the referential and account-state business constraints (`ERR_CONTAINER_LOCATION_MISMATCH`, `ERR_DUPLICATE_BARCODE`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_NO_ACTIVE_RATE_CARD`) round out the chain. The individual trigger conditions are detailed with their workflows below; what matters here is that earlier checks mask later ones.

## 3. Business Logic & Workflows

### 3.1. Accounts, the Billing Clock, and Prepaid Credit

The root of every customer relationship is the **service account**. A `ComplianceOfficer` opens one by supplying a `business_name`, a `compliance_regime` — one of `STANDARD`, `FACTA`, or `HIPAA`, governing how strictly custody and certification are enforced — and a `billing_email` to which invoices are addressed. A new account begins `ACTIVE`, with its deterministic billing clock `current_period_index` set to 0 and its prepaid `storage_credit_cents` balance set to 0.

The account carries a lifecycle of its own, driven by the `ComplianceOfficer`. An `ACTIVE` account can be suspended, moving it to `SUSPENDED`; suspending an account that is not `ACTIVE` is rejected with `ERR_ACCOUNT_NOT_ACTIVE`. A `SUSPENDED` account can be reactivated back to `ACTIVE`; reactivating an account that is not `SUSPENDED` is rejected with `ERR_ACCOUNT_NOT_SUSPENDED`. While an account is `SUSPENDED`, creation of new service orders and new retrieval requests is blocked. Closing an account moves it to `CLOSED` and is permitted only from `ACTIVE` or `SUSPENDED`; an attempt from any other state is rejected with `ERR_ACCOUNT_NOT_CLOSABLE`. A close additionally requires that the account have no retention box still in `INGESTED`, `STORED`, or `OUT_FOR_RETRIEVAL` — otherwise `ERR_OUTSTANDING_BOXES` — and no service order in any non-terminal state — otherwise `ERR_OUTSTANDING_ORDERS`.

Prepaid credit and the billing clock are the two levers the `ComplianceOfficer` uses to manage storage billing. Crediting an account adds a supplied `amount_cents` to `storage_credit_cents`, which is never allowed to go negative and is consumed against storage invoices before cash is due. Advancing the period closes the current billing period: the system first computes and emits the `StorageInvoice` for the period being closed, then advances `current_period_index` by one. The mechanics of that invoice, including how credit is consumed, are described in Section 3.8.

### 3.2. Locations, Rate Cards, and Containers

Each account is served at one or more **service locations**. An `AccountManager` or `ComplianceOfficer` registers a location by supplying its `account_id`, a human-readable `label` such as "HQ 4th Floor", a street `address` for pickup and on-site service, and an optional `secure_area` flag that marks the site as a HIPAA-secured area; when omitted, `secure_area` defaults to false. Locations are reached by listing on `account_id`.

Pricing for an account is governed by its **rate card**. A `ComplianceOfficer` drafts a card against an `account_id` and supplies its rates: `scheduled_purge_rate_cents_per_kg` and `onetime_purge_rate_cents_per_kg` give the per-kilogram destruction rate for scheduled and one-time work respectively (each at least 0); `onsite_trip_fee_cents` is the flat fee added once to any on-site order; `console_swap_fee_cents` is the flat fee charged for each console serviced; `storage_rate_cents_per_box_per_period` is the recurring per-box storage charge per billing period; and `retrieval_fee_cents` is the flat fee per fulfilled retrieval (each of these at least 0). The card also carries a `rush_retrieval_multiplier_bps`, a basis-point multiplier applied to the retrieval fee for rush requests; it defaults to 15000, meaning one and one-half times the base fee, and must be at least 10000 (that is, a rush is never cheaper than a standard retrieval). A card is created in `DRAFT`. When a `ComplianceOfficer` activates it, the card moves to `ACTIVE` and any other card on the same account that was previously `ACTIVE` is moved to `SUPERSEDED`. Activation carries no source-state precondition: it is accepted from any status (a card already `ACTIVE` simply stays `ACTIVE`, and no error is raised for re-activation). Only the single `ACTIVE` card prices new work; a card never returns from `SUPERSEDED`.

Material is collected through **containers** placed at a location. An `AccountManager` or `FieldTechnician` places one by supplying its `account_id`, its `location_id`, a `container_type` of either `CONSOLE` (a locked cabinet) or `BIN` (a rolling toter), a `capacity_kg` nominal fill capacity that must be a whole-number kilogram value strictly greater than 0 (a non-integer `capacity_kg` is rejected with `ERR_INVALID_FIELD_VALUE`), and a `tare_weight_kg` empty weight of at least 0 (which may be fractional) that is subtracted from gross weight at weigh-in. A new container begins `PLACED`. Over its life a container moves through `SCHEDULED_FOR_SERVICE` and `IN_SERVICE` as orders dispatch and complete, returning to `PLACED` when the order finishes, and may finally be retired to `RETIRED`, a terminal state, by an `AccountManager`; retirement carries no source-state precondition and is accepted from any current status.

### 3.3. Opening a Service Order and the Estimated Charge

A **service order** is the unit of destruction work, and it is where the two custody branches and the dual-variant pricing begin. An `AccountManager` or `FieldTechnician` opens one against an `account_id` and a `location_id`, choosing a `service_mode` of `ON_SITE`, `OFF_SITE_PICKUP`, or `DROP_OFF`, and a `cadence` of `SCHEDULED` or `ONE_TIME`. The order names the `container_ids` it will service (optional, but each named container must belong to this order's `account_id` and `location_id`), a `scheduled_slot_start` and a `scheduled_slot_end` as ISO 8601 UTC instants where the end must be strictly after the start, and optionally an `assigned_tech_id` recording the `FieldTechnician` who will take custody. An order begins in `SCHEDULED` status.

Creating an order requires that the account be `ACTIVE` — otherwise `ERR_ACCOUNT_NOT_ACTIVE` — and that the account have an `ACTIVE` rate card to price the work — otherwise `ERR_NO_ACTIVE_RATE_CARD`. If any named container does not belong to the same account and location as the order, the request is rejected with `ERR_CONTAINER_LOCATION_MISMATCH`. Field sanity (a slot end after its start, valid enum members, and so on) is enforced with `ERR_INVALID_FIELD_VALUE`. At order creation specifically, these checks are evaluated in the following order after the left-to-right existence checks: field-value sanity for the enum members (`service_mode`, `cadence`) and for the slot instants (parseable ISO 8601 with end strictly after start) is validated first, then the container slot-conflict (`ERR_SLOT_CONFLICT`), then the on-site buffer (`ERR_ONSITE_BUFFER_CONFLICT`), then the container/location mismatch (`ERR_CONTAINER_LOCATION_MISMATCH`), then the account-active check (`ERR_ACCOUNT_NOT_ACTIVE`), and finally the active-rate-card check (`ERR_NO_ACTIVE_RATE_CARD`).

At creation the charge is computed provisionally, using the **estimated variant** of the destruction charge. The estimated billed weight `billed_weight_kg` is taken as the sum of `capacity_kg` across the order's named containers — a nominal estimate, since nothing has yet been weighed — and `order_charge_cents` computed from it is provisional. The full charge formula, shared by both the estimated and the actual variants, is given in Section 3.7. On creation each named container moves from `PLACED` to `SCHEDULED_FOR_SERVICE`.

Two scheduling constraints guard order creation, and the same two guard rescheduling. The first is the **container slot conflict**: a new or rescheduled order's window must not overlap any other non-terminal order that shares any container. These windows are treated as half-open intervals running from the start up to but not including the end, so two windows that merely touch — one ending exactly when the other begins — do not conflict; a genuine overlap is rejected with `ERR_SLOT_CONFLICT`. The second is the **on-site buffer conflict**, which applies only among non-terminal on-site orders at the same `location_id`: each such order's window is expanded by a thirty-minute buffer on each side — that is, the window runs from thirty minutes before its start to thirty minutes after its end — and the expanded windows are compared as closed intervals, so even buffered endpoints that just touch are treated as a conflict, rejected with `ERR_ONSITE_BUFFER_CONFLICT`.

Rescheduling an order to a new `scheduled_slot_start` and `scheduled_slot_end` is performed by an `AccountManager` and is the optimistic-concurrency-guarded operation: the request carries `expected_serviceorder_version`, the stale-version check runs first as described in Section 2.8 and yields `ERR_STALE_VERSION` on a mismatch, and on success the order's slot is updated and its `version` increments by one. Reschedule imposes no order-lifecycle-state precondition of its own beyond the stale-version, field-sanity, and slot checks; there is no dedicated "order not reschedulable" rejection. The same slot-conflict and on-site-buffer checks that guard creation are re-applied to the new window, with the order itself excluded from those comparisons.

### 3.4. Dispatch, Pickup, and Drop-Off: the Custody Branches

Once scheduled, an order proceeds down one of two custody branches depending on its `service_mode`, and the custody chain records every hop as an immutable `CustodyEvent`. Each event carries an `order_id`, a polymorphic `subject_type` of `CONTAINER` or `RETENTION_BOX` together with the `subject_id` of the container or box in custody, an `event_type` naming the hop, a one-based `sequence_no` that increases monotonically within the order's chain ordered by creation, and the `actor_id` of the operator who logged it. The hop vocabulary is `SEALED`, `COLLECTED`, `IN_TRANSIT`, `RECEIVED_AT_PLANT`, `DESTROYED`, and `RETURNED`.

For on-site and off-site-pickup orders, a `FieldTechnician` first dispatches the order, advancing it from `SCHEDULED` to `EN_ROUTE`. Dispatch is defined only for orders in `SCHEDULED` (otherwise `ERR_ORDER_NOT_SCHEDULED`) whose `service_mode` is `ON_SITE` or `OFF_SITE_PICKUP` — a `DROP_OFF` order never dispatches, and an attempt is rejected with `ERR_DISPATCH_NOT_APPLICABLE`. Dispatch is also blocked if the order is under an active compliance hold (`ERR_SUBJECT_ON_HOLD`). On dispatch, each serviced container moves from `SCHEDULED_FOR_SERVICE` to `IN_SERVICE`, and one `CustodyEvent` of type `COLLECTED` and `subject_type` `CONTAINER` is appended per serviced container, each receiving the next one-based `sequence_no`.

From `EN_ROUTE`, the two modes diverge. An on-site order is shredded in place by a `FieldTechnician`, advancing `EN_ROUTE` to the terminal `ON_SITE_SHREDDED`; this is defined only when the order is in `EN_ROUTE` (otherwise `ERR_ORDER_NOT_EN_ROUTE`), only when `service_mode` is `ON_SITE` (otherwise `ERR_MODE_NOT_ON_SITE`), and only when at least one weight ticket already exists for the order (otherwise `ERR_WEIGH_IN_REQUIRED`). An off-site-pickup order is instead confirmed for pickup by a `FieldTechnician`, advancing `EN_ROUTE` to `PICKED_UP`; this is defined only from `EN_ROUTE` (otherwise `ERR_ORDER_NOT_EN_ROUTE`) and only when `service_mode` is `OFF_SITE_PICKUP` (otherwise `ERR_MODE_NOT_OFF_SITE`). Confirming an off-site pickup appends, per serviced container, a `CustodyEvent` of type `SEALED` followed by one of type `IN_TRANSIT`, with the `SEALED` hop always ordered before the `IN_TRANSIT` hop.

A drop-off order takes a different path: it is never dispatched, and the customer brings the material in directly. A `FieldTechnician` confirms the drop-off straight from `SCHEDULED` to `PICKED_UP`; this is defined only when the order is in `SCHEDULED` (otherwise `ERR_ORDER_NOT_DROP_OFF_READY`), only when `service_mode` is `DROP_OFF` (otherwise `ERR_MODE_NOT_DROP_OFF`), and only when the order is under no active compliance hold (otherwise `ERR_SUBJECT_ON_HOLD`). On a drop-off confirmation each serviced container moves from `SCHEDULED_FOR_SERVICE` to `IN_SERVICE`, and per serviced container a `CustodyEvent` of type `SEALED` is appended followed by one of type `IN_TRANSIT`, in that order.

### 3.5. Weigh-In and the Plant Destruction Branch

Before destruction can be finalized, the material must be weighed. A `FieldTechnician` or `PlantOperator` records a weigh-in against the order — accepted in any order lifecycle state, since recording a ticket carries no order-status precondition — producing a **weight ticket** — an append-only record carrying the order's `order_id`, the scale's `gross_weight_kg` (which must be at least 0), the computed `tare_total_kg`, the computed `net_weight_kg`, and the `captured_by` identifier of the operator who recorded it. The **net-weight calculation** sums the `tare_weight_kg` of every container listed in the parent order's `container_ids` — regardless of each container's current status — to obtain `tare_total_kg`, then sets `net_weight_kg` to the gross weight minus that tare total, with the result held to three decimal places of a kilogram and floored at zero so it can never go negative.

Off-site-pickup and drop-off orders converge at the plant. A `PlantOperator` receives a `PICKED_UP` order at the plant, advancing it to `AT_PLANT`; this is defined only from `PICKED_UP` (otherwise `ERR_ORDER_NOT_PICKED_UP`) and only when at least one weight ticket exists for the order (otherwise `ERR_WEIGH_IN_REQUIRED`). Receiving at the plant recomputes the charge using the actual variant — `billed_weight_kg` is set to the weight ticket's `net_weight_kg` and `order_charge_cents` is recomputed and finalized — and appends one `CustodyEvent` of type `RECEIVED_AT_PLANT` per serviced container.

The final destruction at the plant is performed by a `DestructionWitness`, advancing `AT_PLANT` to the terminal `DESTROYED`. This is defined only from `AT_PLANT` (otherwise `ERR_ORDER_NOT_AT_PLANT`), only when no active compliance hold names the order (otherwise `ERR_SUBJECT_ON_HOLD`), and only when segregation of duties is satisfied: the witnessing operator's `X-User-ID`, supplied on the request as `witnessed_by`, must differ from the order's recorded `assigned_tech_id` — the collector may not also witness — otherwise the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. On destruction, one `CustodyEvent` of type `DESTROYED` is appended per serviced container, each serviced container moves from `IN_SERVICE` back to `PLACED`, and the order is finalized, triggering the destruction cascade described in Section 3.6.

### 3.6. Finalization: the Destruction Certificate and Invoice Cascade

Both terminal destruction paths — on-site shredding and witnessed plant destruction — finalize the order's billing and then run an identical three-hop cascade. The first hop finalizes the order: `billed_weight_kg` is set to the relevant weight ticket's `net_weight_kg` (for on-site shredding this happens at the shred step; for the plant branch it happened at receive-at-plant) and `order_charge_cents` is recomputed under the actual variant, replacing the provisional estimate. The second hop auto-issues a **destruction certificate** in status `ISSUED`, carrying the order's `order_id` and `account_id`, a server-minted string `certificate_no` that is monotonic per account in order of issuance, a `destroyed_weight_kg` snapshot equal to the order's finalized `billed_weight_kg`, and a `witnessed_by` identifier recorded at issuance — the on-site technician for an on-site shred, the witness for a plant destruction. The third hop, fired by the certificate's issuance, creates a **destruction invoice** in status `ISSUED`, carrying the order's `order_id` and `account_id`, the `certificate_id` of the certificate that triggered it, and a `line_cents` snapshot equal to the order's finalized `order_charge_cents`. A `ComplianceOfficer` may later mark a destruction invoice paid, setting its status to `PAID`; this action carries no source-state precondition and is applied unconditionally regardless of the invoice's current status (there is no rejection for an already-paid invoice).

A `ComplianceOfficer` may void an issued certificate, setting its status to `VOIDED`; like the pay action, voiding carries no source-state precondition and is applied unconditionally regardless of the certificate's current status (there is no rejection for an already-voided certificate). The certificate's existence also gates cancellation, as the next paragraph explains.

An order may be cancelled by an `AccountManager` while it is still early in its life — specifically while it is in `SCHEDULED` or `EN_ROUTE`; a cancel attempt from any other state is rejected with `ERR_ORDER_NOT_CANCELLABLE`. Cancellation is further refused if a destruction certificate already exists for the order, with `ERR_CERTIFICATE_ALREADY_ISSUED`. A cancellation is a compensating action: every serviced container reverts to `PLACED`, which conserves the global count of placed containers against the pre-dispatch baseline, and the order's `order_charge_cents` and `billed_weight_kg` are both reset to 0, fully reversing the provisional charge. Cancellation moves the order to the terminal `CANCELLED`.

### 3.7. The Destruction Charge Calculation

The destruction charge is computed in a pinned order from three independent components and is the same formula whether evaluated provisionally at order creation or finally at weigh-in; only the source of `billed_weight_kg` differs between the two variants. It is always priced from the account's single `ACTIVE` rate card.

The first and largest component is the weight charge. The per-kilogram rate is selected by cadence: a `SCHEDULED` order uses `scheduled_purge_rate_cents_per_kg`, while a `ONE_TIME` order uses `onetime_purge_rate_cents_per_kg`. The weight charge in cents is `billed_weight_kg` multiplied by that selected per-kilogram rate, with the product rounded half up to an integer number of cents. The second component is the trip fee: an `ON_SITE` order adds `onsite_trip_fee_cents` once, while any other mode adds nothing for the trip. The third component is the console fee: it is `console_swap_fee_cents` multiplied by the number of `CONSOLE`-type containers among the order's named `container_ids` (bins do not attract this fee). The three components are then summed — weight charge first, then trip fee, then console fee — to produce `order_charge_cents`. The cadence branch (which rate) and the mode branch (whether a trip fee applies) are independent inputs that both feed the final sum.

The two variants differ only in where `billed_weight_kg` comes from. Under the **estimated variant**, evaluated at order creation before any weight ticket exists, `billed_weight_kg` is the sum of `capacity_kg` across the named containers and the resulting `order_charge_cents` is provisional. Under the **actual variant**, evaluated at on-site shred (for on-site orders) or at receive-at-plant (for off-site-pickup and drop-off orders), `billed_weight_kg` is the weight ticket's `net_weight_kg` — gross minus summed tare — and the resulting `order_charge_cents` is final, replacing the estimate.

### 3.8. Retention Boxes, Storage Billing, and the Free Period

The warehouse side of the business stores sealed **retention boxes**. An `AccountManager` or `PlantOperator` ingests a box by supplying its `account_id`, its `location_id` (the originating site of the contents), and a client-supplied `barcode`. The barcode must be unique among the account's boxes whose status is not `DESTROYED`; a collision is rejected with `ERR_DUPLICATE_BARCODE`, and the barcode is freed for reuse once a box is destroyed. Ingest may also set `free_periods`, the number of initial billing periods exempt from storage charges (defaulting to 0 and required to be at least 0), and optionally `destroy_after_period`, the earliest period at which purge is permitted (when omitted, the box is retained indefinitely). At ingest the box is recorded as `INGESTED`, and `stored_at_period` is snapshotted to the account's current `current_period_index` to serve as the storage-billing baseline.

A `PlantOperator` shelves an ingested box, moving it from `INGESTED` to `STORED` (an attempt on a box not in `INGESTED` is rejected with `ERR_BOX_NOT_INGESTED`); shelving brings the box into the storage-billable set, subject to the free-period boundary. While a retrieval is out, the box is in `OUT_FOR_RETRIEVAL` but remains storage-billable — only destruction removes a box from billing. An `AccountManager` purges a stored box, moving `STORED` to the terminal `DESTROYED`; a purge on a box not in `STORED` is rejected with `ERR_BOX_NOT_STORED`. Purge is gated by two checks evaluated in order: first, that no active compliance hold names the box (`ERR_SUBJECT_ON_HOLD`, checked before the retention schedule); and second, when the box has a `destroy_after_period` set, that the account's `current_period_index` has reached at least that period — otherwise the retention clock has not elapsed and the purge is rejected with `ERR_RETENTION_NOT_ELAPSED`. On purge the box leaves the storage-billable set and its barcode is freed.

Storage is billed one period at a time when a `ComplianceOfficer` closes a period. Let the closing period be the account's `current_period_index` as it stands before the increment. The **storage-invoice calculation** first determines the billable boxes: those whose status is `STORED` or `OUT_FOR_RETRIEVAL` (boxes still `INGESTED` and boxes already `DESTROYED` are excluded) and whose free period has elapsed — that is, the closing period is greater than or equal to the box's `stored_at_period` plus its `free_periods` (the boundary is inclusive). The `storage_line_cents` is `storage_rate_cents_per_box_per_period` multiplied by the count of billable boxes. The `retrieval_line_cents` is the sum of `retrieval_charge_cents` across every retrieval request whose `delivered_period` equals the closing period — these were priced when each retrieval was fulfilled. The gross for the period is `storage_line_cents` plus `retrieval_line_cents`. The credit applied is the smaller of the account's `storage_credit_cents` and that gross, recorded as `credit_applied_cents`; the account's `storage_credit_cents` is then reduced by exactly that amount, so the credit consumed plus the credit remaining equals the credit that was on hand before close. The `amount_due_cents` is the gross minus `credit_applied_cents` and is never negative. The resulting `StorageInvoice` records the `account_id`, the `period_index` it covers, and these computed lines. When the account holds no credit, `credit_applied_cents` is 0 and `amount_due_cents` equals the gross. After the invoice is emitted, `current_period_index` advances by one. A `ComplianceOfficer` may later mark a storage invoice paid, setting its status to `PAID`; this action carries no source-state precondition and is applied unconditionally regardless of the invoice's current status. Closing a period is a pricing operation and therefore requires an `ACTIVE` rate card on the account; without one, the close is rejected with `ERR_NO_ACTIVE_RATE_CARD`.

### 3.9. Retrieval Requests and the Rush Surcharge

When a customer needs a stored box pulled, an `AccountManager` opens a **retrieval request** against a `box_id` and `account_id`, choosing a `priority` of `STANDARD` or `RUSH` and recording the `requested_by` identifier. A new request begins `PENDING` with its `delivered_period` set to -1 until it is fulfilled. The full set of statuses a retrieval request may carry is `PENDING`, `DELIVERED`, `RETURN_PENDING`, `RETURNED`, `REFUSED`, and `CANCELLED`. Opening a request requires the account to be `ACTIVE`, otherwise `ERR_ACCOUNT_NOT_ACTIVE`.

A `PlantOperator` fulfills a pending request, advancing it from `PENDING` to `DELIVERED`. Fulfillment is defined only when the request is in `PENDING` (otherwise `ERR_REQUEST_NOT_PENDING`), only when the target box is in `STORED` (otherwise `ERR_BOX_NOT_STORED`), and only when no active compliance hold names the box (otherwise `ERR_SUBJECT_ON_HOLD`); pricing it also requires an `ACTIVE` rate card (otherwise `ERR_NO_ACTIVE_RATE_CARD`). On fulfillment the **retrieval-charge calculation** runs against the `ACTIVE` rate card: the base is `retrieval_fee_cents`, and for a `STANDARD` request the charge is exactly that base, while for a `RUSH` request the charge is the base multiplied by `rush_retrieval_multiplier_bps` and divided by ten thousand, with the result rounded half up to an integer cent. The computed amount is snapshotted onto `retrieval_charge_cents`, `delivered_period` is set to the account's current `current_period_index` (pinning which storage invoice the charge lands on), and the box moves from `STORED` to `OUT_FOR_RETRIEVAL`.

The return cycle has a deliberate revert. An `AccountManager` starts a return on a delivered request, moving `DELIVERED` to `RETURN_PENDING` (an attempt on a request not in `DELIVERED` is rejected with `ERR_REQUEST_NOT_DELIVERED`). A `PlantOperator` then completes the return, moving `RETURN_PENDING` to the terminal `RETURNED` and moving the box from `OUT_FOR_RETRIEVAL` back to `STORED`; a return when the box is not in `OUT_FOR_RETRIEVAL` is rejected with `ERR_BOX_NOT_OUT`. Alternatively, if the returned box fails inspection — for instance, a broken seal — a `PlantOperator` may refuse the return, cycling `RETURN_PENDING` back to `DELIVERED` and leaving the box `OUT_FOR_RETRIEVAL`, so the customer must restart the return. Both completing and refusing a return require the request to be in `RETURN_PENDING`, otherwise `ERR_RETURN_NOT_PENDING`. A pending request that is no longer wanted may be cancelled by an `AccountManager`, moving `PENDING` to the terminal `CANCELLED`; a cancel on a request not in `PENDING` is rejected with `ERR_REQUEST_NOT_CANCELLABLE`.

### 3.10. Compliance Holds Across Boxes and Orders

A `ComplianceOfficer` freezes a box or an order by placing a **compliance hold**. The hold is created against an `account_id`, with a polymorphic `subject_type` of `RETENTION_BOX` or `SERVICE_ORDER` naming what is frozen and a `subject_id` identifying the held box or order, and a `reason` of `LITIGATION_HOLD`, `AUDIT_HOLD`, or `REGULATORY_FREEZE`. A hold begins `ACTIVE`. While it is `ACTIVE`, the named subject cannot be destroyed or purged, an order cannot be dispatched, a retrieval against a held box cannot be fulfilled, and a drop-off cannot be confirmed; every one of these is the `ERR_SUBJECT_ON_HOLD` rejection raised in the workflow it guards. A `ComplianceOfficer` releases a hold, moving `ACTIVE` to the terminal `RELEASED` and removing the gate; releasing a hold that is not `ACTIVE` is rejected with `ERR_HOLD_NOT_ACTIVE`. Holds, weight tickets, and the custody log together form the audit record an inspector relies on, retrievable by listing on the relevant foreign keys.

## 4. Endpoint Definitions

Operations that create a new, standalone resource — opening an account, drafting a rate card, placing a container, opening an order, recording a weigh-in, ingesting a box, opening a retrieval request, placing a hold — return `201 Created`, as does closing a billing period, which emits a new storage invoice. Operations that modify an existing resource, including every state transition and every payment or release action, return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Create a service account | ComplianceOfficer |
| GET | `/accounts/{id}` | Get a service account | ComplianceOfficer, AccountManager |
| GET | `/accounts` | List service accounts | ComplianceOfficer |
| POST | `/accounts/{id}/credit` | Add prepaid storage credit | ComplianceOfficer |
| POST | `/accounts/{id}/advance-period` | Close current period; emit storage invoice, then advance the clock | ComplianceOfficer |
| POST | `/accounts/{id}/suspend` | Suspend account | ComplianceOfficer |
| POST | `/accounts/{id}/reactivate` | Reactivate account | ComplianceOfficer |
| POST | `/accounts/{id}/close` | Close account | ComplianceOfficer |
| POST | `/locations` | Create a service location | AccountManager, ComplianceOfficer |
| GET | `/locations/{id}` | Get a service location | AccountManager, ComplianceOfficer |
| GET | `/locations` | List locations (filter by account_id) | AccountManager, ComplianceOfficer |
| POST | `/rate-cards` | Create a rate card in DRAFT | ComplianceOfficer |
| GET | `/rate-cards/{id}` | Get a rate card | ComplianceOfficer, AccountManager |
| GET | `/rate-cards` | List rate cards (filter by account_id, status) | ComplianceOfficer, AccountManager |
| POST | `/rate-cards/{id}/activate` | Activate a rate card; supersede the prior active card | ComplianceOfficer |
| POST | `/containers` | Place a bin/console at a location | AccountManager, FieldTechnician |
| GET | `/containers/{id}` | Get a container | AccountManager, FieldTechnician, ComplianceOfficer |
| GET | `/containers` | List containers (filter by account_id, location_id, status) | AccountManager, FieldTechnician, ComplianceOfficer |
| POST | `/containers/{id}/retire` | Retire a container | AccountManager |
| POST | `/service-orders` | Create a service order | AccountManager, FieldTechnician |
| GET | `/service-orders/{id}` | Get a service order | AccountManager, FieldTechnician, PlantOperator, DestructionWitness, ComplianceOfficer |
| GET | `/service-orders` | List service orders (filter by account_id, location_id, status) | AccountManager, FieldTechnician, PlantOperator, ComplianceOfficer |
| POST | `/service-orders/{id}/reschedule` | Reschedule the slot (OCC-guarded) | AccountManager |
| POST | `/service-orders/{id}/dispatch` | Dispatch field tech | FieldTechnician |
| POST | `/service-orders/{id}/weigh-in` | Record a weight ticket for the order | FieldTechnician, PlantOperator |
| GET | `/weight-tickets/{id}` | Get a weight ticket | FieldTechnician, PlantOperator, ComplianceOfficer |
| GET | `/weight-tickets` | List weight tickets (filter by order_id) | FieldTechnician, PlantOperator, ComplianceOfficer |
| POST | `/service-orders/{id}/shred-on-site` | On-site shred branch | FieldTechnician |
| POST | `/service-orders/{id}/confirm-pickup` | Off-site pickup / drop-off intake | FieldTechnician |
| POST | `/service-orders/{id}/receive-at-plant` | Plant intake | PlantOperator |
| POST | `/service-orders/{id}/destroy` | Witnessed plant destruction (SoD enforced) | DestructionWitness |
| POST | `/service-orders/{id}/cancel` | Cancel order (compensating revert) | AccountManager |
| GET | `/custody-events/{id}` | Get a single custody event | FieldTechnician, PlantOperator, DestructionWitness, ComplianceOfficer |
| GET | `/custody-events` | Chain-of-custody log (filter by order_id) | FieldTechnician, PlantOperator, DestructionWitness, ComplianceOfficer |
| GET | `/certificates/{id}` | Get a certificate of destruction | AccountManager, ComplianceOfficer |
| GET | `/certificates` | List certificates (filter by order_id, account_id, status) | AccountManager, ComplianceOfficer |
| POST | `/certificates/{id}/void` | Void an issued certificate | ComplianceOfficer |
| GET | `/destruction-invoices/{id}` | Get a destruction invoice | ComplianceOfficer, AccountManager |
| GET | `/destruction-invoices` | List destruction invoices (filter by order_id, account_id, certificate_id, status) | ComplianceOfficer, AccountManager |
| POST | `/destruction-invoices/{id}/pay` | Mark a destruction invoice paid | ComplianceOfficer |
| POST | `/retention-boxes` | Ingest a retention box | AccountManager, PlantOperator |
| GET | `/retention-boxes/{id}` | Get a retention box | AccountManager, PlantOperator, ComplianceOfficer |
| GET | `/retention-boxes` | List retention boxes (filter by account_id, location_id, status) | AccountManager, PlantOperator, ComplianceOfficer |
| POST | `/retention-boxes/{id}/shelve` | Shelve an ingested box | PlantOperator |
| POST | `/retention-boxes/{id}/purge` | Purge a stored box | AccountManager |
| POST | `/retrieval-requests` | Open a retrieval request against a box | AccountManager |
| GET | `/retrieval-requests/{id}` | Get a retrieval request | AccountManager, PlantOperator, ComplianceOfficer |
| GET | `/retrieval-requests` | List retrieval requests (filter by box_id, account_id, status) | AccountManager, PlantOperator, ComplianceOfficer |
| POST | `/retrieval-requests/{id}/fulfill` | Fulfill a retrieval (charge snapshot) | PlantOperator |
| POST | `/retrieval-requests/{id}/start-return` | Begin box return | AccountManager |
| POST | `/retrieval-requests/{id}/return` | Complete box return | PlantOperator |
| POST | `/retrieval-requests/{id}/refuse-return` | Refuse return (box stays out) | PlantOperator |
| POST | `/retrieval-requests/{id}/cancel` | Cancel a pending retrieval | AccountManager |
| POST | `/compliance-holds` | Place a litigation/audit/regulatory hold | ComplianceOfficer |
| GET | `/compliance-holds/{id}` | Get a compliance hold | ComplianceOfficer, AccountManager |
| GET | `/compliance-holds` | List compliance holds (filter by account_id, subject_id, status) | ComplianceOfficer, AccountManager |
| POST | `/compliance-holds/{id}/release` | Release a hold | ComplianceOfficer |
| GET | `/storage-invoices/{id}` | Get a storage invoice | ComplianceOfficer, AccountManager |
| GET | `/storage-invoices` | List storage invoices (filter by account_id, period_index, status) | ComplianceOfficer, AccountManager |
| POST | `/storage-invoices/{id}/pay` | Mark a storage invoice paid | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_BOX_NOT_FOUND` | 404 Not Found |
| `ERR_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ORDER_NOT_SCHEDULED` | 409 Conflict |
| `ERR_ORDER_NOT_EN_ROUTE` | 409 Conflict |
| `ERR_ORDER_NOT_DROP_OFF_READY` | 409 Conflict |
| `ERR_ORDER_NOT_PICKED_UP` | 409 Conflict |
| `ERR_ORDER_NOT_AT_PLANT` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_DISPATCH_NOT_APPLICABLE` | 409 Conflict |
| `ERR_MODE_NOT_ON_SITE` | 409 Conflict |
| `ERR_MODE_NOT_OFF_SITE` | 409 Conflict |
| `ERR_MODE_NOT_DROP_OFF` | 409 Conflict |
| `ERR_WEIGH_IN_REQUIRED` | 409 Conflict |
| `ERR_CERTIFICATE_ALREADY_ISSUED` | 409 Conflict |
| `ERR_SUBJECT_ON_HOLD` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_RETENTION_NOT_ELAPSED` | 409 Conflict |
| `ERR_SLOT_CONFLICT` | 409 Conflict |
| `ERR_ONSITE_BUFFER_CONFLICT` | 409 Conflict |
| `ERR_BOX_NOT_INGESTED` | 409 Conflict |
| `ERR_BOX_NOT_STORED` | 409 Conflict |
| `ERR_BOX_NOT_OUT` | 409 Conflict |
| `ERR_REQUEST_NOT_PENDING` | 409 Conflict |
| `ERR_REQUEST_NOT_DELIVERED` | 409 Conflict |
| `ERR_RETURN_NOT_PENDING` | 409 Conflict |
| `ERR_REQUEST_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_HOLD_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_SUSPENDED` | 409 Conflict |
| `ERR_ACCOUNT_NOT_CLOSABLE` | 409 Conflict |
| `ERR_OUTSTANDING_BOXES` | 409 Conflict |
| `ERR_OUTSTANDING_ORDERS` | 409 Conflict |
| `ERR_CONTAINER_LOCATION_MISMATCH` | 409 Conflict |
| `ERR_DUPLICATE_BARCODE` | 409 Conflict |
| `ERR_INVALID_FIELD_VALUE` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_RATE_CARD` | 409 Conflict |
