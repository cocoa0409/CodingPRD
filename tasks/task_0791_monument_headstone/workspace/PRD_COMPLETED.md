# Monument & Headstone Service API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Monument & Headstone Service API, a back-office platform that carries a memorial marker — for a human or a pet — from an initial customer order all the way through engraving design, fabrication, cemetery permitting, on-site installation, and post-installation restoration under warranty. The domain is unusual in that a single order is governed simultaneously by two independent lifecycles: how far the physical marker has progressed through production, and how much of its contracted price the customer has paid. These two axes advance on their own schedules and gate one another only at specific checkpoints — a marker cannot be handed over until it is paid in full, yet a proof cannot be approved until at least the deposit has cleared.

The platform coordinates five operational parties — the shop that provisions reference data, the customer, the design studio, the fabrication/restoration shop, and the field installation crew — each of whom touches the order at a different stage. Along the way the system must enforce hard physical and regulatory constraints (a granite marker that is too tall for its destination cemetery may never be produced), protect shared capacity (a workshop or a crew cannot be double-booked), and keep a precise financial ledger in which every cent of deposit, balance, and refund reconciles. Money, schedule, compliance, and state must all remain internally consistent after every mutation, including the cascading teardown that follows a cancellation.

The sections below define the global contract that every endpoint shares (§2), the detailed business workflows and their scattered rules (§3), the endpoint catalogue (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, envelopes, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a header that is malformed, is rejected with `ERR_MISSING_USER_CONTEXT`. The system recognizes exactly five roles, spelled precisely as `Admin`, `Customer`, `Designer`, `ShopManager`, and `FieldOps`. When a role attempts an operation it is not authorized to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Only one role is tied to a persisted identity. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the owning order's `customer_id` to `X-User-ID`. Concretely, for customer-scoped writes — creating an order, cancelling an order, recording a payment, approving or requesting changes on a design proof, and requesting a restoration — the acting customer's `X-User-ID` must equal the `customer_id` of the owning order (for order creation, the `customer_id` supplied in the request body), and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`.

The other four roles carry opaque identifiers. When `X-User-Role` is `Admin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. The same holds when `X-User-Role` is `Designer`, when `X-User-Role` is `ShopManager`, and when `X-User-Role` is `FieldOps`: in each case `X-User-ID` is an opaque operator identifier, not tied to a persisted entity and not subject to ownership comparison. `Admin` provisions cemeteries, customers, workshops, and crews, and drives the logical clock. `Designer` authors and revises engraving proofs. `ShopManager` schedules and completes fabrication and assesses restoration. `FieldOps` handles permits and installation. All five roles may perform every read (`GET`) operation.

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

List endpoints are paginated through two query parameters. The `limit` parameter bounds the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources are addressable, versioned entities. Cemeteries, customers, monument orders, design proofs, workshops, fabrication jobs, cemetery permits, installation crews, installations, and restoration jobs each carry a system-generated `id` formatted as a bare UUID with no type prefix, a `created_at` timestamp (ISO 8601 UTC with three fractional digits), an `updated_at` timestamp in the same format that is refreshed on every mutation, and an integer `version` that starts at its initial value and increments by one on each modification.

The one exception is the `Payment` resource. A payment is immutable once captured and therefore carries only `id` and `created_at`; it has neither an `updated_at` nor a `version` field. Whenever a payment is created, the reconciliation of `amount_paid_cents` and the possible advance of the order's `payment_status` are recorded as a mutation of the owning `MonumentOrder`, not of the payment.

Because a derived value changing is itself a mutation, any server-initiated recomputation on a `MonumentOrder` — recalculating its price after a proof is approved, reconciling its paid amount after a payment, opening its warranty window at installation — refreshes the order's `updated_at` and increments its `version`.

### 2.5. Monetary and Dimensional Precision

All monetary amounts are expressed in whole integer cents, and all rounding uses the round-half-up convention (a value ending in exactly one-half cent rounds up to the next whole cent). Where a calculation composes several steps, the point at which rounding is applied is significant and is specified per calculation in §3; implementers must round at exactly the stated step and not earlier or later, because rounding a sum is not equivalent to summing rounded parts. Surface areas are computed and compared in whole square centimetres, and slot durations are computed in whole minutes.

### 2.6. Cemetery-Spec Compliance

Every cemetery publishes the envelope of markers it will accept: an `allowed_materials` list drawn from `GRANITE`, `BRONZE`, and `MARBLE`, and three inclusive dimensional ceilings — `max_height_cm`, `max_width_cm`, and `max_base_width_cm`. An order's chosen `material` must be a member of the destination cemetery's `allowed_materials`; a material outside that set is rejected with `ERR_MATERIAL_NOT_ALLOWED`. The marker's `height_cm` must not exceed `max_height_cm`, its `width_cm` must not exceed `max_width_cm`, and its foundation `base_width_cm` must not exceed `max_base_width_cm`; any dimension that overshoots its ceiling is rejected with `ERR_EXCEEDS_CEMETERY_SPEC`. These compliance checks are enforced both when an order is created and again when a permit is issued, so that a marker whose destination specs have tightened cannot slip through to placement.

### 2.7. Capacity, Scheduling Windows, and Slot Conflicts

Shared production and installation capacity is protected by non-overlap rules, and every scheduled slot must be well-formed: its `scheduled_end` must be strictly after its `scheduled_start`, or the request is rejected with `ERR_INVALID_SCHEDULE_WINDOW`. A slot's `duration_minutes` is the number of whole minutes between its start and end.

Workshops enforce a half-open non-overlap rule. A new fabrication or restoration slot occupies the interval from its start up to but not including its end; it may not overlap any interval already committed on that same workshop, where the committed set is every `SCHEDULED` fabrication job plus every `ASSESSED` restoration job on the workshop. Because the interval is half-open, two slots that merely touch — one ending at the exact instant the next begins — are permitted. A genuine overlap is rejected with `ERR_WORKSHOP_SLOT_CONFLICT`.

Installation crews enforce a stricter buffered rule. Two installation slots on the same crew must be separated by at least a one-hour turnaround — that is, sixty minutes — so a proposed slot is acceptable only if its start is at least sixty minutes after some existing slot's end, or its end plus sixty minutes is at or before some existing slot's start. Adjacency is therefore not allowed for crews: back-to-back slots that touch violate the buffer. A violation is rejected with `ERR_CREW_SLOT_CONFLICT`.

Each workshop and each crew exposes a derived `booked_minutes` figure. A workshop's `booked_minutes` is always exactly the sum of `duration_minutes` across its `SCHEDULED` fabrication jobs and its `ASSESSED` restoration jobs; a crew's `booked_minutes` is the sum of `duration_minutes` across its `SCHEDULED` installations. These figures move up as slots are booked and back down as slots complete or are cancelled, and they must never drift away from that defining sum.

### 2.8. Optimistic Concurrency Control on Proof Creation

Creating a new design proof is guarded by optimistic concurrency control against the owning order. A create-proof request must include `expected_order_version`, carrying the `version` of the target `MonumentOrder` that the client last observed. If that value does not equal the order's current `version`, the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). This matters because each proof creation legitimately supersedes the order's prior current proof and advances the order's `version`; a create that still carries a previously observed version is working from a stale view of the order and would risk overwriting a proof the client never saw. No other endpoint takes a version field; proof creation is the sole optimistic-concurrency checkpoint.

### 2.9. Cascading State Consistency

Some operations mutate more than one resource in a single, immediately consistent step, and every secondary effect must land atomically with the primary transition. The most extensive of these is order cancellation, whose four-level cascade is described in §3.7; smaller cascades accompany fabrication completion, installation completion, and restoration assessment, each of which adjusts a capacity figure alongside a status change. Wherever a transition releases booked capacity, the affected workshop or crew `booked_minutes` is decreased by the released slot's `duration_minutes` at the same moment. Every such reconciliation that touches a `MonumentOrder` increments its `version` and refreshes its `updated_at`, per §2.4.

### 2.10. Validation Ordering and Nested Retrieval

When an endpoint's path or body carries resource identifiers, existence is validated left to right, and the first identifier that does not resolve yields its own not-found error — `ERR_ORDER_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_CEMETERY_NOT_FOUND`, `ERR_PROOF_NOT_FOUND`, `ERR_WORKSHOP_NOT_FOUND`, `ERR_FAB_JOB_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_INSTALLATION_NOT_FOUND`, or `ERR_RESTORATION_NOT_FOUND` as appropriate. A reverse-reach listing such as an order's proofs, payments, fabrication jobs, permits, installations, or restorations first confirms the parent order exists before returning the child collection.

The validation stages are applied in a fixed precedence, so that a request failing several checks always surfaces the highest-precedence failure. The order is: first, the presence and validity of the user-context headers (`ERR_MISSING_USER_CONTEXT`); then the role's authorization for the operation (`ERR_FORBIDDEN_ROLE`); then, for customer-scoped writes, resource ownership (`ERR_NOT_RESOURCE_OWNER`); then existence of every referenced id (the 404 family above); then request well-formedness — required fields present, enum members valid, schedule window valid, and a permit's `cemetery_id` equal to its order's `cemetery_id` — surfacing `ERR_INVALID_REQUEST` or `ERR_INVALID_SCHEDULE_WINDOW`; then the target resource being in the correct state for the transition (the 409 state family); then cemetery-spec compliance (`ERR_MATERIAL_NOT_ALLOWED` / `ERR_EXCEEDS_CEMETERY_SPEC`, HTTP 422); then the installation temporal-readiness check (`ERR_INSTALL_BEFORE_FAB_READY`); then resource slot-conflict checks (`ERR_WORKSHOP_SLOT_CONFLICT` / `ERR_CREW_SLOT_CONFLICT`); then the cross-entity readiness gates (`ERR_PROOF_NOT_APPROVED` / `ERR_PERMIT_NOT_ISSUED`); then fiscal sufficiency (`ERR_DEPOSIT_NOT_PAID` / `ERR_BALANCE_NOT_PAID` / `ERR_ZERO_PAYMENT_AMOUNT`, HTTP 402); and finally the optimistic-concurrency check on proof creation (`ERR_STALE_ORDER_VERSION`, HTTP 412).

### 2.11. The Logical Clock

The server keeps a logical clock rather than reading wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any override it never falls back to real time. An `Admin` may advance it by supplying a `to_iso8601` instant. The logical clock supplies the `completed_at` stamps written when fabrication jobs and installations complete, and it is the "now" against which a restoration's warranty window is judged.

## 3. Business Logic & Workflows

### 3.1. Provisioning Reference Data

Before any order can exist, an `Admin` provisions the supporting catalogue. A cemetery is registered with its `name`, its `allowed_materials`, and its three dimensional ceilings `max_height_cm`, `max_width_cm`, and `max_base_width_cm`; it also records `requires_permit` (whether a placement permit must be issued before installation, defaulting to true), a `permit_fee_cents` flat charge (defaulting to 0) that is folded into an order's contract when a permit is required, and `requires_foundation` (whether a concrete foundation and setting is mandated, defaulting to true). A customer is registered with `full_name`, `email`, and an optional `phone`. Workshops and installation crews are each registered with just a `name`; both begin with `booked_minutes` initialized to zero.

### 3.2. Placing an Order and Provisional Pricing

A `Customer` opens a `MonumentOrder` by naming the owning `customer_id`, the destination `cemetery_id`, the `subject_type` (`HUMAN` or `PET`), the `material`, the marker's `height_cm` and `width_cm`, the foundation `base_width_cm`, and an `estimated_line_char_counts` array — one positive integer per anticipated engraving line — used to price the order provisionally. The order is born with `production_status` at `DRAFTING` and `payment_status` at `UNPAID`. Cemetery-spec compliance is checked at this moment as described in §2.6. The acting customer's `X-User-ID` must equal the supplied `customer_id`, or the request is rejected with `ERR_NOT_RESOURCE_OWNER`; for order creation specifically this ownership check is evaluated only after the referenced `customer_id` and `cemetery_id` are confirmed to exist and the body is well-formed, so a non-existent entity surfaces its 404 and a malformed body surfaces `ERR_INVALID_REQUEST` ahead of the ownership check.

At creation the system prices the marker under the **provisional variant** and records the result in `provisional_merchandise_cents`. Pricing has two parts, a material component and an engraving component, combined into the merchandise price.

The engraving component is computed line by line. For the subject type, the per-character rate is 250 cents for a `HUMAN` marker and 180 cents for a `PET` marker. Each engraving line is priced by multiplying its character count by that rate and then applying a 15 percent volume discount — that is, retaining 85 percent of the line's gross — and rounding the result half up to whole cents. The rounded per-line amounts are then summed. The rounding happens on each line before summation, not once on the total; summing the character counts first and rounding once would yield a different, incorrect figure. For the provisional variant, the character counts come from the order's `estimated_line_char_counts`.

The material component starts from the marker's face area, the product of `height_cm` and `width_cm`, in square centimetres. That face area is multiplied by the per-square-centimetre material rate — 8 cents for `GRANITE`, 15 cents for `BRONZE`, and 11 cents for `MARBLE` — to give a raw material component. A size tier multiplier is then applied based on face area: a face area of at least 6000 square centimetres takes a 125 percent multiplier, a face area of at least 3000 but under 6000 takes a 110 percent multiplier, and anything below 3000 takes a 100 percent multiplier (no uplift). The raw material component multiplied by the tier percentage and divided by one hundred is rounded half up to whole cents to give the priced material figure. The merchandise price is that priced material figure plus the summed engraving charge.

Once the merchandise price is known, the contract is assembled. `merchandise_price_cents` at creation equals `provisional_merchandise_cents`. To it the system adds a flat foundation and setting charge of 45,000 cents, and, when the destination cemetery requires a permit, the cemetery's `permit_fee_cents` (when no permit is required, no permit fee is added). That sum is `contract_total_cents`. The `deposit_amount_cents` is 40 percent of the contract total, rounded half up to whole cents in a single rounding step. The `balance_amount_cents` is the exact remainder — the contract total minus the deposit — with no independent rounding, so that deposit plus balance always equals the contract total exactly. The order's `amount_paid_cents` begins at zero and `warranty_expires_at` is null until installation.

### 3.3. The Engraving Proof Revision Cycle

A `Designer` authors an engraving proof against an order by creating a `DesignProof` that carries the `order_id`, the `expected_order_version` demanded by §2.8, the `engraving_text`, a `line_char_counts` array (one positive integer per engraving line), and an optional `layout_spec` note. A new proof is born in `DRAFT` with `revision_round` at 1 and immediately becomes the order's `current_proof_id`. If the order already had a current proof in `DRAFT`, `SUBMITTED`, or `CHANGES_REQUESTED`, that prior proof is retired to `SUPERSEDED` so exactly one proof is current; a current proof already in `APPROVED` (or any terminal state) is left untouched and keeps its status even as the new `DRAFT` proof takes over as `current_proof_id`. The order's `version` is incremented on every proof creation.

A proof moves through a revision loop. Submitting a proof advances it from `DRAFT` to `SUBMITTED`, presenting it to the customer; a submit attempted on a proof that is neither `DRAFT` nor `CHANGES_REQUESTED` is rejected with `ERR_PROOF_NOT_DRAFT`. A `Customer` reviewing a submitted proof may request edits, moving it from `SUBMITTED` to `CHANGES_REQUESTED`; a request-changes on a proof not in `SUBMITTED` is rejected with `ERR_PROOF_NOT_SUBMITTED`. The designer then re-submits, carrying the proof from `CHANGES_REQUESTED` back to `SUBMITTED` and incrementing its `revision_round` by one — this is the cycle that lets a proof iterate. Because the same submit action serves both the initial and the repeat submission, a re-submit from a state other than `CHANGES_REQUESTED` (or `DRAFT`) likewise fails with `ERR_PROOF_NOT_DRAFT`.

Approval closes the loop. A `Customer` approves a submitted proof, moving it from `SUBMITTED` to `APPROVED`. Approval is permitted only when the owning order is still in `DRAFTING` (otherwise `ERR_ORDER_NOT_DRAFTING`), when the proof being approved is the order's current proof (otherwise `ERR_PROOF_NOT_CURRENT`), and when the deposit has already been paid — the order's `payment_status` is not `UNPAID` (otherwise `ERR_DEPOSIT_NOT_PAID`). An approve attempted on a proof not in `SUBMITTED` is rejected with `ERR_PROOF_NOT_SUBMITTED`. Approving a proof re-prices the marker under the **final variant**: the engraving charge is recomputed exactly as in §3.2 but drawing its line character counts from the approved proof's `line_char_counts` rather than the order's estimate, and the result is written to `merchandise_price_cents`. The contract is then re-assembled — `contract_total_cents`, `deposit_amount_cents`, and `balance_amount_cents` recomputed from the new merchandise price by the same rules — and the order's `version` is incremented. Approval does not by itself advance `production_status`; the order remains `DRAFTING`, and it is the scheduling of fabrication that moves it out of `DRAFTING`. A consequence worth noting is that a `DRAFTING` order can still carry a merely `SUBMITTED` (not yet approved) proof. The approve endpoint responds with the approved `DesignProof` resource (not the order), even though its side effects re-price and re-version the owning order.

### 3.4. Deposit, Balance, and the Payment Ledger

Payment flows through an append-only ledger of `Payment` records against the order. A `Customer` records a payment by supplying the `order_id`, a `payment_type`, and an `amount_cents`. Client-supplied payments are of type `DEPOSIT` or `BALANCE`; a third type, `REFUND`, is only ever generated by the system during cancellation. Every payment is captured synchronously, so its `status` is `CAPTURED` at creation. Each payment carries a `signed_amount_cents`: a `DEPOSIT` or `BALANCE` contributes plus its `amount_cents`, while a `REFUND` contributes minus its `amount_cents`. The order's `amount_paid_cents` is always exactly the sum of `signed_amount_cents` over that order's `CAPTURED` payments; it is recomputed on every payment, and each payment increments the order's `version`.

For any `DEPOSIT` or `BALANCE`, the `amount_cents` must be strictly greater than zero, or the request is rejected with `ERR_ZERO_PAYMENT_AMOUNT`. A `DEPOSIT` payment advances the order's payment axis from `UNPAID` to `DEPOSIT_PAID`, but only if the cumulative captured `amount_paid_cents` after the payment reaches at least `deposit_amount_cents`; a deposit that leaves the paid amount short of the deposit is rejected with `ERR_DEPOSIT_NOT_PAID`. A `BALANCE` payment advances the axis to `PAID_IN_FULL` — from `DEPOSIT_PAID`, or directly from `UNPAID` when a single balance already covers the whole contract — but only if the cumulative captured `amount_paid_cents` after the payment reaches at least `contract_total_cents`; a balance that leaves the paid amount short of the full contract is rejected with `ERR_BALANCE_NOT_PAID`. The payment axis is independent of production: it runs `UNPAID → DEPOSIT_PAID → PAID_IN_FULL` (the intermediate `DEPOSIT_PAID` step may be skipped when a balance paid from `UNPAID` immediately reaches the full contract), with `REFUNDED` reachable only through cancellation.

### 3.5. Fabrication and Turnaround

Once a proof is approved and the deposit is in hand, a `ShopManager` schedules fabrication by supplying the `order_id`, the executing `workshop_id`, and a `scheduled_start` and `scheduled_end`. Scheduling fabrication is the transition that carries the order from `DRAFTING` to `IN_FABRICATION`, and it is subject to several preconditions. The order must be in `DRAFTING` (otherwise `ERR_ORDER_NOT_DRAFTING`); the order's current proof must be `APPROVED` (otherwise `ERR_PROOF_NOT_APPROVED`) — note that approving a proof does not itself advance production, so this cross-entity gate is what enforces that an approved design exists before the shop begins; and the requested slot must not conflict on the workshop under the half-open rule of §2.7 (otherwise `ERR_WORKSHOP_SLOT_CONFLICT`). On success a `FabricationJob` is created in `SCHEDULED` status, its `duration_minutes` is computed from the slot, the workshop's `booked_minutes` is increased by that duration, the order advances to `IN_FABRICATION`, and the order's `version` is incremented.

When fabrication is finished, the `ShopManager` completes the job, which must be in `SCHEDULED` (otherwise `ERR_FAB_JOB_NOT_SCHEDULED`). Completion stamps the job's `completed_at` from the logical clock, moves the job from `SCHEDULED` to `COMPLETED`, releases the slot by decreasing the workshop's `booked_minutes` by the job's `duration_minutes`, advances the order from `IN_FABRICATION` to `READY_TO_INSTALL`, and increments the order's `version`.

### 3.6. Permitting, Installation, and the Warranty Window

Placement at a cemetery is coordinated by `FieldOps`. A permit is opened for an order by supplying the `order_id`, the `cemetery_id`, the cemetery-assigned `permit_number`, and a `placement_date` — the earliest date the marker may be placed. The supplied `cemetery_id` must equal the order's own `cemetery_id`, or the request is malformed (`ERR_INVALID_REQUEST`). A new `CemeteryPermit` begins `PENDING`. Issuing a permit re-checks cemetery-spec compliance against the order's current marker dimensions and material per §2.6 (rejecting with `ERR_EXCEEDS_CEMETERY_SPEC` or `ERR_MATERIAL_NOT_ALLOWED`) and requires the permit to be `PENDING` (otherwise `ERR_PERMIT_NOT_PENDING`); it then moves the permit from `PENDING` to `ISSUED`, making it usable as an installation precondition.

`FieldOps` schedules installation by supplying the `order_id`, the performing `crew_id`, and a `scheduled_start` and `scheduled_end`. Installation requires the order to be `READY_TO_INSTALL` with a `COMPLETED` fabrication job on record; an order that is not yet ready (no completed fabrication) is rejected with `ERR_INSTALL_BEFORE_FAB_READY`. When the destination cemetery requires a permit, an `ISSUED` permit must exist for the order (otherwise `ERR_PERMIT_NOT_ISSUED`). The installation's `scheduled_start` must be at or after the order's fabrication `completed_at` and at or after the issued permit's `placement_date`; a start that precedes either readiness point is rejected with `ERR_INSTALL_BEFORE_FAB_READY`. The crew slot must satisfy the sixty-minute buffered separation of §2.7 (otherwise `ERR_CREW_SLOT_CONFLICT`). On success an `Installation` is created in `SCHEDULED`, its `duration_minutes` is computed, and the crew's `booked_minutes` is increased by that duration.

Completing an installation is the moment the marker is handed over, and it is gated on payment. The installation must be `SCHEDULED` (otherwise `ERR_INSTALLATION_NOT_SCHEDULED`), and the order must be `PAID_IN_FULL` (otherwise `ERR_BALANCE_NOT_PAID`). Completion stamps the installation's `completed_at` from the logical clock, moves it from `SCHEDULED` to `COMPLETED`, releases the crew slot by decreasing the crew's `booked_minutes` by the installation's `duration_minutes`, advances the order from `READY_TO_INSTALL` to `INSTALLED`, and opens the warranty window by setting `warranty_expires_at`. The warranty length depends on the subject: a `HUMAN` marker carries a ten-year warranty (120 months) and a `PET` marker a five-year warranty (60 months), each measured forward in calendar months from the installation's `completed_at`. The order's `version` is incremented.

### 3.7. Cancellation and the Refund Cascade

A `Customer` may cancel an order at any point before it is terminal — that is, while `production_status` is `DRAFTING`, `IN_FABRICATION`, or `READY_TO_INSTALL`. A cancel attempted on an order already `INSTALLED` or `CANCELLED` is rejected with `ERR_ORDER_ALREADY_TERMINAL`. Cancellation moves the order to `CANCELLED` and runs a four-level teardown that must leave every dependent resource and every capacity figure consistent. Any `SCHEDULED` fabrication job for the order is moved to `CANCELLED`, and that job's `duration_minutes` is released from its workshop's `booked_minutes`. Any `SCHEDULED` installation for the order is moved to `CANCELLED`, and its `duration_minutes` is released from its crew's `booked_minutes`. Any `PENDING` or `ISSUED` permit for the order is moved to `REVOKED`. Every non-terminal design proof for the order — those in `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED`, or `APPROVED` — is moved to `VOIDED`.

The refund branch closes out the money. If the order's `amount_paid_cents` is greater than zero at cancellation, the system creates a `REFUND` payment for the negative of the paid amount, so that recomputing `amount_paid_cents` over the captured ledger returns it to zero, and the order's `payment_status` moves to `REFUNDED`. This compensating entry keeps the money invariant intact: the paid amount is always the signed sum of the ledger. The order's `version` is incremented for the cancellation.

### 3.8. Restoration, Cleaning, and Warranty Claims

After a monument is installed it can be brought back for restoration. A `Customer` requests a restoration by supplying the `order_id`, a `service_type` (`CLEANING`, `REPAIR`, or `REFINISH`), an optional `is_warranty` flag (defaulting to false) indicating a warranty claim, and a customer-reported `reported_area_cm2`. No production-status precondition is enforced at request time — a restoration may be requested against an order in any production state, including one not yet `INSTALLED` (the `INSTALLED` requirement applies only to the warranty waiver evaluated at assessment). The job is born `REQUESTED`, and the system records a provisional **quoted** cost: `quoted_cost_cents` is the reported area multiplied by the per-square-centimetre service rate — 2 cents for `CLEANING`, 6 cents for `REPAIR`, and 9 cents for `REFINISH`. At request time no surcharge and no warranty waiver apply; `workshop_id`, `measured_area_cm2`, `condition`, `scheduled_start`, `scheduled_end`, `duration_minutes`, and `assessed_cost_cents` remain null while the job is `REQUESTED`.

A `ShopManager` then assesses the job, which must be `REQUESTED` (otherwise `ERR_RESTORATION_NOT_REQUESTED`), supplying the `workshop_id`, the shop-`measured_area_cm2`, the `condition` (`NORMAL` or `SEVERE`), and a `scheduled_start` and `scheduled_end` for the workshop slot. The slot is subject to the same half-open workshop non-overlap rule as fabrication (otherwise `ERR_WORKSHOP_SLOT_CONFLICT`). Assessment moves the job from `REQUESTED` to `ASSESSED`, computes its `duration_minutes`, and increases the workshop's `booked_minutes` by that duration. It also finalizes the cost under the **assessed** variant: if the claim is under warranty and the owning order is `INSTALLED` and the logical clock now is at or before the order's `warranty_expires_at` — an inclusive boundary — the assessed cost is waived to zero. Otherwise the assessed cost is the measured area multiplied by the service rate, plus a flat surcharge of 5,000 cents when the `condition` is `SEVERE`. The result is written to `assessed_cost_cents`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that transition or otherwise modify an existing resource, including all state-machine actions and the logical-clock set, return `200 OK`. Reads return `200 OK`. Every request body and side effect is described in §3 and §2; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/memorials/cemeteries` | Register a cemetery and its marker specs | Admin |
| POST | `/memorials/customers` | Register a customer | Admin |
| POST | `/memorials/workshops` | Register a fabrication/restoration workshop | Admin |
| POST | `/memorials/crews` | Register an installation crew | Admin |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving) | Admin |
| POST | `/memorials/orders` | Create a monument order; prices provisional variant and deposit | Customer |
| GET | `/memorials/orders/{id}` | Fetch an order | All roles |
| GET | `/memorials/orders` | List orders, filterable by cemetery_id / customer_id | All roles |
| POST | `/memorials/orders/{id}/cancel` | Cancel an order; runs the cancel cascade and refund | Customer |
| POST | `/memorials/design-proofs` | Create an engraving design proof (OCC on order version) | Designer |
| GET | `/memorials/orders/{id}/design-proofs` | List an order's design proofs | All roles |
| POST | `/memorials/design-proofs/{id}/submit` | Submit or re-submit a proof | Designer |
| POST | `/memorials/design-proofs/{id}/approve` | Approve a submitted proof; recomputes final price | Customer |
| POST | `/memorials/design-proofs/{id}/request-changes` | Request changes on a submitted proof | Customer |
| POST | `/memorials/payments` | Record a deposit or balance payment | Customer |
| GET | `/memorials/orders/{id}/payments` | List an order's payments | All roles |
| POST | `/memorials/fabrication-jobs` | Schedule fabrication; advances order to IN_FABRICATION | ShopManager |
| GET | `/memorials/fabrication-jobs/{id}` | Fetch a fabrication job | All roles |
| GET | `/memorials/fabrication-jobs` | List fabrication jobs, filterable by order_id / workshop_id | All roles |
| POST | `/memorials/fabrication-jobs/{id}/complete` | Complete fabrication; advances order to READY_TO_INSTALL | ShopManager |
| POST | `/memorials/permits` | Open a placement permit for an order | FieldOps |
| GET | `/memorials/permits/{id}` | Fetch a permit | All roles |
| GET | `/memorials/permits` | List permits, filterable by order_id / cemetery_id | All roles |
| POST | `/memorials/permits/{id}/issue` | Issue a pending permit after re-checking compliance | FieldOps |
| POST | `/memorials/installations` | Schedule foundation/setting + installation on a crew | FieldOps |
| GET | `/memorials/installations/{id}` | Fetch an installation | All roles |
| GET | `/memorials/installations` | List installations, filterable by order_id / crew_id | All roles |
| POST | `/memorials/installations/{id}/complete` | Complete installation; advances order to INSTALLED | FieldOps |
| POST | `/memorials/restorations` | Request restoration; prices the provisional quote | Customer |
| GET | `/memorials/restorations/{id}` | Fetch a restoration job | All roles |
| GET | `/memorials/restorations` | List restoration jobs, filterable by order_id / workshop_id | All roles |
| POST | `/memorials/restorations/{id}/assess` | Assess a restoration, schedule it, and finalize cost | ShopManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_CEMETERY_NOT_FOUND` | 404 Not Found |
| `ERR_PROOF_NOT_FOUND` | 404 Not Found |
| `ERR_WORKSHOP_NOT_FOUND` | 404 Not Found |
| `ERR_FAB_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_NOT_FOUND` | 404 Not Found |
| `ERR_INSTALLATION_NOT_FOUND` | 404 Not Found |
| `ERR_RESTORATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_SCHEDULE_WINDOW` | 400 Bad Request |
| `ERR_ZERO_PAYMENT_AMOUNT` | 402 Payment Required |
| `ERR_MATERIAL_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_EXCEEDS_CEMETERY_SPEC` | 422 Unprocessable Entity |
| `ERR_ORDER_NOT_DRAFTING` | 409 Conflict |
| `ERR_ORDER_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_PROOF_NOT_DRAFT` | 409 Conflict |
| `ERR_PROOF_NOT_SUBMITTED` | 409 Conflict |
| `ERR_PROOF_NOT_CURRENT` | 409 Conflict |
| `ERR_PROOF_NOT_APPROVED` | 409 Conflict |
| `ERR_FAB_JOB_NOT_SCHEDULED` | 409 Conflict |
| `ERR_INSTALLATION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_PERMIT_NOT_PENDING` | 409 Conflict |
| `ERR_PERMIT_NOT_ISSUED` | 409 Conflict |
| `ERR_RESTORATION_NOT_REQUESTED` | 409 Conflict |
| `ERR_INSTALL_BEFORE_FAB_READY` | 409 Conflict |
| `ERR_WORKSHOP_SLOT_CONFLICT` | 409 Conflict |
| `ERR_CREW_SLOT_CONFLICT` | 409 Conflict |
| `ERR_DEPOSIT_NOT_PAID` | 402 Payment Required |
| `ERR_BALANCE_NOT_PAID` | 402 Payment Required |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
